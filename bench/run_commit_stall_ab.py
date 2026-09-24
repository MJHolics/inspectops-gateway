"""주기적 2.5초 멈춤의 원인 A/B — PostgreSQL 커밋의 fsync 대기인가?

관찰(threads_bench): 약 30초마다 그 순간 in-flight 요청 전부가 +2.5s. 추론 호출 타이머 ≤0.63s,
GC 최대 13ms, Hikari 획득 최대 0.1s → 남는 건 DB 트랜잭션 커밋.
가설: 커널 dirty writeback(주기 30s)이 가상 디스크를 막는 순간 WAL fsync가 밀려 커밋이 멈춘다.

검증: 같은 조건(platform, VUS=200, 주입지연 500ms, 90초 = 30초 주기 3번)에서
  A) synchronous_commit=on (기본)  vs  B) synchronous_commit=off (커밋이 WAL fsync를 기다리지 않음)
B에서 꼬리가 사라지면 원인은 커밋 fsync다. 각 조건 2회씩 ABBA 순서로.

결과: results/commit_stall_ab.json
"""
import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_threads_bench as tb  # noqa: E402

ROOT = tb.ROOT
OUT = ROOT / "results" / "commit_stall_ab.json"


def set_sync_commit(value):
    tb.sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-c",
           f"ALTER SYSTEM SET synchronous_commit = '{value}'"])
    tb.sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-c",
           "SELECT pg_reload_conf()"])
    got = tb.sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-At", "-c",
                 "SHOW synchronous_commit"]).stdout.strip()
    assert got == value, got


def stall_histogram():
    q = ("select count(*) filter (where ms > 2000), count(*), round(max(ms)) from "
         "(select extract(epoch from completed_at-created_at)*1000 ms from inspection where line_id='LOAD') t")
    return tb.sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-At", "-c", q]).stdout.strip()


def main():
    cfg = {"name": "platform", "VIRTUAL_THREADS": "false", "OPEN_IN_VIEW": "false"}
    tb.restart_stack(cfg, 500)
    tb.k6(20, "10s")
    results = []
    for value in ["on", "off", "off", "on"]:
        set_sync_commit(value)
        tb.sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-c",
               "delete from inspection where line_id='LOAD'"])
        row = {"synchronous_commit": value, **tb.k6(200, "90s")}
        slow, total, mx = stall_histogram().split("|")
        row.update({"db_slow_gt_2s": int(slow), "db_total": int(total), "db_max_ms": float(mx)})
        print(json.dumps(row), flush=True)
        results.append(row)
        OUT.write_text(json.dumps({"runs": results}, indent=2), "utf-8")
    set_sync_commit("on")


if __name__ == "__main__":
    main()
