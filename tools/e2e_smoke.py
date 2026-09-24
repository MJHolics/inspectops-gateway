"""e2e 스모크 — 실제 스택(PostgreSQL + ONNX 추론 + Gateway)에 샘플 이미지를 전부 흘려 본다.

접수 → 추론 → 게이트(0.80) → 검토 큐 → 사람 확정 → 라인별 집계 → 메트릭까지 한 번에 확인한다.
결과는 results/e2e_smoke.json에 남긴다.

사용: python tools/e2e_smoke.py [--base http://localhost:8080]
"""
import argparse
import json
import time
from collections import Counter
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    args = ap.parse_args()

    samples = sorted((ROOT / "samples").glob("*.jpg"))
    rows = []
    with httpx.Client(base_url=args.base, timeout=30) as c:
        for i, p in enumerate(samples):
            line = f"L{i % 3 + 1}"
            t0 = time.perf_counter()
            r = c.post("/api/v1/inspections", data={"lineId": line},
                       files={"image": (p.name, p.read_bytes(), "image/jpeg")})
            ms = (time.perf_counter() - t0) * 1000
            r.raise_for_status()
            b = r.json()
            rows.append({"file": p.name, "line": line, "status": b["status"],
                         "class": b["defectClass"], "confidence": b["confidence"],
                         "model_ms": b["inferenceMs"], "e2e_ms": round(ms, 1), "id": b["id"]})

        # 깨진 입력 — 추론 서비스가 422로 거부 → 재시도 없이 FAILED
        bad = c.post("/api/v1/inspections", data={"lineId": "L1"},
                     files={"image": ("broken.jpg", b"not an image", "image/jpeg")}).json()

        queue = c.get("/api/v1/inspections", params={"status": "NEEDS_REVIEW"}).json()
        reviewed = None
        if queue["content"]:
            first = queue["content"][0]
            reviewed = c.post(f"/api/v1/inspections/{first['id']}/review",
                              json={"finalClass": first["defectClass"], "reviewer": "e2e"}).json()
        stats = c.get("/api/v1/stats").json()
        prom = c.get("/actuator/prometheus").text

    status_count = Counter(r["status"] for r in rows)
    e2e = sorted(r["e2e_ms"] for r in rows)
    out = {
        "n": len(rows),
        "status_count": status_count,
        "broken_input": {"status": bad["status"], "attempts": bad["attempts"], "error": bad["errorMessage"]},
        "review_queue_size_before": queue["page"]["totalElements"] if "page" in queue else None,
        "reviewed": reviewed and {"status": reviewed["status"], "reviewedClass": reviewed["reviewedClass"]},
        "stats": stats,
        "e2e_ms_p50": e2e[len(e2e) // 2],
        "e2e_ms_max": e2e[-1],
        "metric_lines": [l for l in prom.splitlines() if l.startswith("inspectops_inspections_total")],
        "rows": rows,
    }
    (ROOT / "results").mkdir(exist_ok=True)
    (ROOT / "results" / "e2e_smoke.json").write_text(json.dumps(out, ensure_ascii=False, indent=2), "utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "rows"}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
