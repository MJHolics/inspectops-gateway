"""스레드 모델 × Open-In-View × 동시성 부하 실측.

질문: 추론이 느릴 때(주입 지연 EXTRA_LATENCY_MS) Gateway의 처리량 상한을 정하는 건 무엇인가?
  - Tomcat 플랫폼 스레드 200개인가 (→ 가상 스레드로 풀리는가)
  - DB 커넥션 풀 10개인가 (→ Open-In-View가 느린 호출 동안 커넥션을 쥐고 있는가)

설정마다 gateway 컨테이너를 환경변수만 바꿔 재기동하고, 워밍업 후 동시성 단계별로 k6를 돌린다.
단계가 끝날 때마다 results/threads_bench.json에 즉시 덧붙여 쓴다(중간에 죽어도 끝난 단계는 남는다).

사용: python bench/run_threads_bench.py [--latency-ms 500] [--duration 30s]
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "threads_bench.json"
NETWORK = "inspectops-gateway_default"

CONFIGS = [
    {"name": "platform", "VIRTUAL_THREADS": "false", "OPEN_IN_VIEW": "false"},
    {"name": "virtual", "VIRTUAL_THREADS": "true", "OPEN_IN_VIEW": "false"},
    {"name": "platform+osiv", "VIRTUAL_THREADS": "false", "OPEN_IN_VIEW": "true"},
    {"name": "virtual+osiv", "VIRTUAL_THREADS": "true", "OPEN_IN_VIEW": "true"},
]
LEVELS = [50, 200, 400, 800]


def sh(cmd, env=None, check=True):
    return subprocess.run(cmd, cwd=ROOT, env=env, check=check, capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def wait_health(timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if httpx.get("http://localhost:8080/actuator/health", timeout=2).json().get("status") == "UP":
                return
        except Exception:
            pass
        time.sleep(1)
    raise RuntimeError("gateway health timeout")


def restart_stack(cfg, latency_ms):
    import os
    env = dict(os.environ)
    env.update({"VIRTUAL_THREADS": cfg["VIRTUAL_THREADS"], "OPEN_IN_VIEW": cfg["OPEN_IN_VIEW"],
                "EXTRA_LATENCY_MS": str(latency_ms)})
    sh(["docker", "compose", "up", "-d", "--force-recreate", "inference", "gateway"], env=env)
    wait_health()


def k6(vus, duration):
    summary = "/results/_k6_summary.json"
    cmd = ["docker", "run", "--rm", "--network", NETWORK,
           "-v", f"{ROOT / 'bench'}:/bench", "-v", f"{ROOT / 'samples'}:/samples",
           "-v", f"{ROOT / 'results'}:/results",
           "grafana/k6:latest", "run", "--quiet", "--summary-export", summary,
           "-e", "BASE=http://gateway:8080", "-e", f"VUS={vus}", "-e", f"DURATION={duration}",
           "/bench/load.js"]
    sh(cmd, check=False)
    m = json.loads((ROOT / "results" / "_k6_summary.json").read_text("utf-8"))["metrics"]
    dur = m["http_req_duration"]
    checks = m.get("checks", {})
    return {
        "vus": vus,
        "requests": int(m["http_reqs"]["count"]),
        "rps": round(m["http_reqs"]["rate"], 1),
        "p50_ms": round(dur["p(50)"], 1),
        "p90_ms": round(dur["p(90)"], 1),
        "p99_ms": round(dur["p(99)"], 1),
        "max_ms": round(dur["max"], 1),
        "http_failed_rate": round(m["http_req_failed"]["value"], 4),
        "checks_pass_rate": round(checks.get("value", float("nan")), 4),
    }


def gateway_db_state():
    """부하 후 FAILED 건수·에러 메시지 샘플 — 실패가 '어디서' 났는지 보려고."""
    q = ("select status, count(*) from inspection where line_id='LOAD' group by status;"
         "select left(error_message,120) from inspection where line_id='LOAD' and status='FAILED' limit 2;")
    r = sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-At", "-c", q],
           check=False)
    return r.stdout.strip()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--latency-ms", type=int, default=500)
    ap.add_argument("--duration", default="30s")
    ap.add_argument("--configs", default=",".join(c["name"] for c in CONFIGS))
    args = ap.parse_args()

    OUT.parent.mkdir(exist_ok=True)
    data = json.loads(OUT.read_text("utf-8")) if OUT.exists() else {"runs": []}
    data["meta"] = {"injected_latency_ms": args.latency_ms, "duration": args.duration,
                    "tomcat_max_threads": 200, "db_pool": 10, "levels": LEVELS,
                    "load": "k6 closed model, same docker network"}

    wanted = set(args.configs.split(","))
    for cfg in CONFIGS:
        if cfg["name"] not in wanted:
            continue
        print(f"== {cfg['name']}", flush=True)
        restart_stack(cfg, args.latency_ms)
        sh(["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "inspectops", "-c",
            "delete from inspection where line_id='LOAD'"], check=False)
        k6(20, "10s")  # 워밍업(JIT·커넥션) — 기록 안 함
        for vus in LEVELS:
            row = {"config": cfg["name"], **k6(vus, args.duration)}
            row["db_after"] = gateway_db_state()
            print(json.dumps(row, ensure_ascii=False), flush=True)
            data["runs"].append(row)
            OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


if __name__ == "__main__":
    main()
