"""results/threads_bench.json → 마크다운 표.

처리량은 k6 rate가 아니라 `requests / 30s`로 계산한다. k6 rate는 분모에 종료 대기(gracefulStop,
느린 설정에서 최대 +33s)를 넣어 느린 설정을 과소평가한다. 반대로 requests는 종료 대기 중 끝난
요청(≤ VUS개)을 포함하므로 최대 VUS/requests 만큼 과대평가된다 — 표에 그 상한을 같이 적는다.
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
d = json.loads((ROOT / "results" / "threads_bench.json").read_text("utf-8"))
dur = int(d["meta"]["duration"].rstrip("s"))

print(f"주입 지연 {d['meta']['injected_latency_ms']}ms · {dur}s/단계 · Tomcat 200 · DB 풀 10\n")
print("| 설정 | VUs | 요청(30s) | 처리량 req/s | 과대평가 상한 | p50 ms | p99 ms | 실패율 |")
print("|---|---:|---:|---:|---:|---:|---:|---:|")
for r in d["runs"]:
    thr = r["requests"] / dur
    over = r["vus"] / r["requests"] * 100
    print(f"| {r['config']} | {r['vus']} | {r['requests']:,} | {thr:,.0f} | +{over:.1f}% | "
          f"{r['p50_ms']:,.0f} | {r['p99_ms']:,.0f} | {r['http_failed_rate'] * 100:.2f}% |")
