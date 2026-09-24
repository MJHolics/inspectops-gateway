"""K8s에서만 보이는 ~500ms 추론 호출 지연 — 어느 조건이 만드는가.

관찰: 추론 서비스 직접 호출은 1.5~27ms인데 Gateway 타이머는 호출당 평균 0.499s.
compose(16 CPU·플랫폼 스레드)에서는 지연 없음(p50 16ms). K8s 차이: CPU limit 1(availableProcessors=1)·가상 스레드.
조건을 하나씩 바꿔 helm upgrade → 64 VU 30초 → 타이머 평균(Δsum/Δcount)을 잰다.
결과: results/k8s_client_delay.json
"""
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import run_hpa_bench as hb  # noqa: E402

ROOT = hb.ROOT
HELM = r"C:\Users\apple\bin\helm.exe"
OUT = ROOT / "results" / "k8s_client_delay.json"

CASES = [
    ("vt=on,cpu=1", {"gateway.virtualThreads": "true", "gateway.resources.limits.cpu": "1"}),
    ("vt=off,cpu=1", {"gateway.virtualThreads": "false", "gateway.resources.limits.cpu": "1"}),
    ("vt=on,cpu=4", {"gateway.virtualThreads": "true", "gateway.resources.limits.cpu": "4"}),
    ("vt=off,cpu=4", {"gateway.virtualThreads": "false", "gateway.resources.limits.cpu": "4"}),
]


def metrics():
    r = hb.run(["kubectl", "run", "m-probe", "--rm", "-i", "--restart=Never", "--quiet",
                "--image=curlimages/curl:latest", "--", "curl", "-s",
                "http://demo-inspectops-gateway:8080/actuator/prometheus"], check=False)
    vals = {}
    for key in ("inspectops_inference_call_seconds_count", "inspectops_inference_call_seconds_sum"):
        m = re.search(rf"^{key}\{{[^}}]*\}} ([0-9.eE+]+)", r.stdout, re.M)
        vals[key] = float(m.group(1)) if m else 0.0
    return vals


def main():
    ip = hb.run([hb.MINIKUBE, "ip"]).stdout.strip()
    port = hb.run(["kubectl", "get", "svc", "demo-inspectops-gateway", "-o",
                   "jsonpath={.spec.ports[0].nodePort}"]).stdout.strip()
    rows = []
    for label, sets in CASES:
        args = [HELM, "upgrade", "demo", str(ROOT / "charts" / "inspectops"), "--reuse-values", "--wait",
                "--set", "gateway.hpa.enabled=false", "--set", "service.type=NodePort"]
        for k, v in sets.items():
            args += ["--set", f"{k}={v}"]
        hb.run(args)
        hb.run(["kubectl", "rollout", "status", "deploy/demo-inspectops-gateway", "--timeout=180s"])
        k6 = ["docker", "run", "--rm", "--network", "minikube",
              "-v", f"{ROOT / 'bench'}:/bench", "-v", f"{ROOT / 'samples'}:/samples",
              "grafana/k6:latest", "run", "--quiet", "-e", f"BASE=http://{ip}:{port}",
              "-e", "VUS=16", "-e", "DURATION=10s", "/bench/load.js"]
        hb.run(k6, check=False)  # 워밍업
        before = metrics()
        k6[k6.index("VUS=16")] = "VUS=64"
        k6[k6.index("DURATION=10s")] = "DURATION=30s"
        hb.run(k6, check=False)
        after = metrics()
        dn = after["inspectops_inference_call_seconds_count"] - before["inspectops_inference_call_seconds_count"]
        ds = after["inspectops_inference_call_seconds_sum"] - before["inspectops_inference_call_seconds_sum"]
        row = {"case": label, "calls": int(dn), "throughput_rps": round(dn / 30, 1),
               "inference_call_avg_ms": round(ds / dn * 1000, 1) if dn else None}
        print(json.dumps(row), flush=True)
        rows.append(row)
        OUT.write_text(json.dumps({"runs": rows}, indent=2), "utf-8")


if __name__ == "__main__":
    main()
