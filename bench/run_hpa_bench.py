"""K8s(minikube) HPA 실측 — 부하가 걸렸을 때 추론 서비스가 스스로 늘어나고, 늘어난 만큼 처리량이 오르는가.

구성: gateway 1개 고정(HPA 끔) · inference HPA(1→6, CPU 60%) · 파드당 uvicorn 1 worker, CPU limit 500m.
부하: k6가 minikube 도커 네트워크에서 NodePort로 일정 VU를 DURATION 동안 건다.
관측: 10초마다 HPA 상태(현재/목표 레플리카·CPU%)를 기록 + k6 CSV에서 10초 구간별 rps·p95를 계산.

결과: results/hpa_bench.json (타임라인) · results/hpa_k6.csv (원시)

사용: python bench/run_hpa_bench.py --vus 64 --duration 6m
전제: minikube 실행 중, 차트가 release=demo 로 설치돼 있고 gateway Service가 NodePort.
"""
import argparse
import csv
import json
import statistics
import subprocess
import threading
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "results" / "hpa_bench.json"
KUBECTL = "kubectl"
MINIKUBE = r"C:\Users\apple\bin\minikube.exe"


def run(cmd, check=True):
    return subprocess.run(cmd, check=check, capture_output=True, text=True, encoding="utf-8", errors="replace")


def hpa_snapshot(name):
    r = run([KUBECTL, "get", "hpa", name, "-o", "json"], check=False)
    if r.returncode != 0:
        return None
    h = json.loads(r.stdout)
    st = h.get("status", {})
    cpu = None
    for m in st.get("currentMetrics") or []:
        if m.get("type") == "Resource":
            cpu = m["resource"]["current"].get("averageUtilization")
    ready = run([KUBECTL, "get", "deploy", h["spec"]["scaleTargetRef"]["name"], "-o",
                 "jsonpath={.status.readyReplicas}"], check=False).stdout.strip()
    return {"current": st.get("currentReplicas"), "desired": st.get("desiredReplicas"),
            "ready": int(ready or 0), "cpu_pct": cpu}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--vus", type=int, default=64)
    ap.add_argument("--duration", default="6m")
    ap.add_argument("--release", default="demo")
    args = ap.parse_args()

    hpa_name = f"{args.release}-inspectops-inference"
    gw_svc = f"{args.release}-inspectops-gateway"
    ip = run([MINIKUBE, "ip"]).stdout.strip()
    port = run([KUBECTL, "get", "svc", gw_svc, "-o", "jsonpath={.spec.ports[0].nodePort}"]).stdout.strip()
    base = f"http://{ip}:{port}"

    csv_path = ROOT / "results" / "hpa_k6.csv"
    csv_path.unlink(missing_ok=True)
    k6_cmd = ["docker", "run", "--rm", "--network", "minikube",
              "-v", f"{ROOT / 'bench'}:/bench", "-v", f"{ROOT / 'samples'}:/samples",
              "-v", f"{ROOT / 'results'}:/results",
              "grafana/k6:latest", "run", "--quiet", "--out", "csv=/results/hpa_k6.csv",
              "-e", f"BASE={base}", "-e", f"VUS={args.vus}", "-e", f"DURATION={args.duration}",
              "/bench/load.js"]

    timeline = []
    t0 = time.time()
    done = threading.Event()

    def poll():
        while not done.is_set():
            s = hpa_snapshot(hpa_name)
            if s:
                s["t"] = round(time.time() - t0)
                timeline.append(s)
                print(json.dumps(s), flush=True)
            done.wait(10)

    th = threading.Thread(target=poll, daemon=True)
    th.start()
    k6 = run(k6_cmd, check=False)
    done.set()
    th.join()

    # k6 CSV → 10초 구간별 rps·p95·실패율
    buckets = defaultdict(lambda: {"n": 0, "dur": [], "failed": 0})
    first_ts = None
    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            ts = float(row["timestamp"])
            first_ts = ts if first_ts is None else min(first_ts, ts)
            if row["metric_name"] == "http_req_duration":
                buckets[int(ts)]["dur"].append(float(row["metric_value"]))
            elif row["metric_name"] == "http_req_failed" and row["metric_value"] == "1":
                buckets[int(ts)]["failed"] += 1
    windows = defaultdict(lambda: {"n": 0, "dur": [], "failed": 0})
    for sec, b in buckets.items():
        w = (sec - int(first_ts)) // 10 * 10
        windows[w]["dur"] += b["dur"]
        windows[w]["failed"] += b["failed"]
    series = []
    for w in sorted(windows):
        d = sorted(windows[w]["dur"])
        if not d:
            continue
        series.append({"t": w, "rps": round(len(d) / 10, 1),
                       "p50_ms": round(statistics.median(d), 1),
                       "p95_ms": round(d[int(len(d) * 0.95) - 1], 1),
                       "failed": windows[w]["failed"]})

    out = {"meta": {"vus": args.vus, "duration": args.duration, "base": base,
                    "inference_limit_cpu": "500m", "hpa": "1→6 @ CPU 60%", "gateway": "1 replica fixed"},
           "hpa_timeline": timeline, "load_series": series, "k6_rc": k6.returncode,
           "k6_tail": k6.stdout[-2000:]}
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps(series, ensure_ascii=False))


if __name__ == "__main__":
    main()
