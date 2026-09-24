"""주기적 COMMIT 멈춤 — 디스크 I/O 경로인가? PGDATA 디스크 vs tmpfs 대조.

조건 고정: platform · VUS=200 · 주입지연 500ms · 90초(30초 주기 3회). 순서 disk → tmpfs → disk.
판정 지표: DB 기준 처리시간 > 2s 인 요청 수, COMMIT > 1s 로그 건수.
결과: results/tmpfs_ab.json
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_threads_bench as tb  # noqa: E402

ROOT = tb.ROOT
OUT = ROOT / "results" / "tmpfs_ab.json"


def compose(files, *args):
    cmd = ["docker", "compose"]
    for f in files:
        cmd += ["-f", f]
    env = dict(os.environ, VIRTUAL_THREADS="false", OPEN_IN_VIEW="false", EXTRA_LATENCY_MS="500")
    return tb.sh(cmd + list(args), env=env, check=False)


def psql(files, sql):
    return compose(files, "exec", "-T", "postgres", "psql", "-U", "inspectops", "-At", "-c", sql).stdout.strip()


def one(label, files):
    compose(files, "up", "-d", "--force-recreate", "postgres", "inference", "gateway")
    tb.wait_health()
    psql(files, "ALTER SYSTEM SET log_min_duration_statement = 1000")
    psql(files, "SELECT pg_reload_conf()")
    mount = psql(files, "select setting from pg_settings where name='data_directory'")
    fs = compose(files, "exec", "-T", "postgres", "sh", "-c", "df -T /var/lib/postgresql/data | tail -1").stdout.split()
    tb.k6(20, "10s")
    psql(files, "delete from inspection where line_id='LOAD'")
    load = tb.k6(200, "90s")
    slow = psql(files, "select count(*) filter (where extract(epoch from completed_at-created_at) > 2) "
                       "from inspection where line_id='LOAD'")
    logs = compose(files, "logs", "--since", "2m", "postgres").stdout
    commits = [l[-120:] for l in logs.splitlines() if "duration:" in l and "COMMIT" in l]
    row = {"label": label, "pgdata_fs": fs[1] if len(fs) > 1 else "?", "data_directory": mount,
           **load, "db_slow_gt_2s": int(slow or 0), "commit_gt_1s_logs": len(commits),
           "commit_samples": commits[:3]}
    print(json.dumps(row, ensure_ascii=False), flush=True)
    return row


def main():
    base = ["docker-compose.yml"]
    ram = ["docker-compose.yml", "docker-compose.tmpfs.yml"]
    runs = []
    for label, files in [("disk", base), ("tmpfs", ram), ("disk", base)]:
        runs.append(one(label, files))
        OUT.write_text(json.dumps({"runs": runs}, ensure_ascii=False, indent=2), "utf-8")
    compose(base, "up", "-d", "--force-recreate", "postgres", "inference", "gateway")


if __name__ == "__main__":
    main()
