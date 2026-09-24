"""멈춤 진단 2단계 — 멈추는 순간 무엇이 느린가.

1) PostgreSQL: log_min_duration_statement=1000 (1초 넘는 문장 로그), log_lock_waits=on
2) 부하(platform, VUS=200, 70s) 도중 0.5초마다 pg_stat_activity를 떠서
   state·wait_event별로 몇 개가 머무는지 기록 → 멈춘 순간의 스냅샷을 찾는다.
결과: results/stall_probe.json
"""
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_threads_bench as tb  # noqa: E402

ROOT = tb.ROOT


def psql(sql):
    return tb.sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-At", "-c", sql],
                 check=False).stdout.strip()


def main():
    psql("ALTER SYSTEM SET log_min_duration_statement = 1000")
    psql("ALTER SYSTEM SET log_lock_waits = on")
    psql("SELECT pg_reload_conf()")
    tb.restart_stack({"name": "platform", "VIRTUAL_THREADS": "false", "OPEN_IN_VIEW": "false"}, 500)
    tb.k6(20, "10s")
    psql("delete from inspection where line_id='LOAD'")

    snaps = []
    stop = threading.Event()
    t0 = time.time()

    def poll():
        q = ("select coalesce(state,'-')||'/'||coalesce(wait_event_type,'-')||':'||coalesce(wait_event,'-'), "
             "count(*), round(max(extract(epoch from now()-query_start))::numeric,2) "
             "from pg_stat_activity where datname='inspectops' and pid<>pg_backend_pid() group by 1")
        while not stop.is_set():
            out = psql(q)
            snaps.append({"t": round(time.time() - t0, 1), "rows": out.splitlines()})
            stop.wait(0.5)

    th = threading.Thread(target=poll, daemon=True)
    th.start()
    load = tb.k6(200, "70s")
    stop.set()
    th.join()

    # 가장 오래 머문 문장이 1초를 넘긴 스냅샷만 추린다
    hot = [s for s in snaps if any(float(r.split("|")[-1] or 0) > 1.0 for r in s["rows"] if "|" in r)]
    logs = tb.sh(["docker", "compose", "logs", "--since", "3m", "postgres"], check=False).stdout
    slow_lines = [l[-260:] for l in logs.splitlines() if "duration:" in l or "still waiting" in l][:30]
    gw = tb.sh(["docker", "compose", "logs", "--since", "3m", "gateway"], check=False).stdout
    gw_warn = [l[-260:] for l in gw.splitlines() if " WARN " in l or " ERROR " in l][:20]

    out = {"load": load, "hot_snapshots": hot[:40], "n_snapshots": len(snaps),
           "pg_slow_log": slow_lines, "gateway_warn": gw_warn}
    (ROOT / "results" / "stall_probe.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    psql("ALTER SYSTEM RESET log_min_duration_statement")
    psql("ALTER SYSTEM RESET log_lock_waits")
    psql("SELECT pg_reload_conf()")
    print(json.dumps({k: out[k] for k in ("load", "pg_slow_log", "gateway_warn")}, ensure_ascii=False, indent=1))
    print("hot snapshots:", len(hot))
    for s in hot[:12]:
        print(s)


if __name__ == "__main__":
    main()
