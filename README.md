# InspectOps Gateway — 검사 AI를 "서비스"로 운영하는 플랫폼 층

> InspectOps(제조·의료 검사 운영 플랫폼)의 **서비스 층**. 기존 InspectOps는 모듈(엣지 CNN·VLM·코파일럿·
> 이상탐지)을 Python 단일 프로세스 데모로 묶었다 — 작업 접수·상태 저장·배포·확장이 없었다.
> 이 레포가 그 빈칸을 채운다: **Spring Boot Gateway + ONNX 추론 서비스 + PostgreSQL**, Docker·Helm·K8s(HPA).

```
[클라이언트 / 대시보드]
        │ REST (multipart)
[Gateway — Spring Boot 3.5 · Java 21]
  · 검사 접수 → 추론 호출 → 신뢰도 게이트(0.80) → 자동 채택 / 검토 큐
  · PostgreSQL(JPA·Flyway)에 작업 상태 · 사람 검토 확정 API · 라인별 집계
  · 재시도(5xx·연결 실패만) · 타임아웃 · 실패는 FAILED로 기록(판정을 지어내지 않음)
  · Actuator + Micrometer → Prometheus
        │ HTTP
[추론 서비스 — FastAPI · onnxruntime]
  · MobileNetV3-Small 엣지 CNN (NEU 6-class test 99.6%, HF Space 라이브 데모와 같은 모델)
        │
[K8s(minikube) · Helm 차트 · HPA · PostgreSQL StatefulSet(PVC)]
```

## 실행

```bash
docker compose up -d --build          # postgres + inference + gateway
python tools/e2e_smoke.py             # 샘플 24장 e2e → results/e2e_smoke.json
cd gateway && mvn test                # 통합 테스트 9개 (가짜 추론 서버 + H2)
```

K8s:
```bash
minikube start --driver=docker && minikube addons enable metrics-server
minikube image build -t inspectops-gateway:0.1.0 gateway
minikube image build -t inspectops-inference:0.1.0 inference-service
helm install demo charts/inspectops --set service.type=NodePort
```

## API

| 메서드 | 경로 | 설명 |
|---|---|---|
| POST | `/api/v1/inspections` (multipart `lineId`, `image`) | 접수+판정. 추론 실패도 201 + `status=FAILED` (접수 기록은 남는다) |
| GET | `/api/v1/inspections/{id}` | 단건 |
| GET | `/api/v1/inspections?status=NEEDS_REVIEW` | 검토 큐(오래된 순) |
| POST | `/api/v1/inspections/{id}/review` | 사람이 최종 라벨 확정 (두 번 확정 시 409) |
| GET | `/api/v1/stats` | 라인×상태 건수 |
| GET | `/actuator/prometheus` | 메트릭 |

---

## ① 목표 — 왜 만들었나

InspectOps의 검사 모델들은 "돈다"는 건 보였지만 **운영되는 서비스**는 아니었다. 실제 라인에 붙이려면
누가 무엇을 언제 보냈는지 남아야 하고(추적성), 모델이 죽어도 접수 기록은 살아 있어야 하며,
검토가 필요한 건 사람에게 넘어가야 하고, 부하가 오르면 늘어나야 한다. 모델 정확도와는 별개의 문제다.
이 레포는 그 층만 만든다. 판정 로직은 재론하지 않는다(엣지 CNN 99.6%는 `vlm-defect-inspector`가 답했다).

## ② 상품성 — 누가 쓰나

- **검사 라인 운영자**: 사진을 올리면 자동 채택/검토 필요가 나뉘고, 검토 큐에서 사람이 확정한다.
  자동 판정과 사람 확정이 **따로 저장**돼(`defectClass` vs `reviewedClass`) 재학습 라벨로 바로 쓴다.
- **품질/규제 담당**: 모든 요청이 이미지 해시·모델 버전·시도 횟수와 함께 남는다. 추론이 실패하면
  **판정을 지어내지 않고** `FAILED`로 남긴다 — `vision-inspection-agent`에서 파서가 실패를 삼키고
  "주의 0.5"를 날조하던 문제(85.7% 날조)를 서비스 층에서 구조적으로 막는다.
- **플랫폼 운영자**: Helm 한 줄로 설치, 추론은 HPA로 늘고, 메트릭은 Prometheus로 나간다.

## ③ 설계 근거

| 결정 | 대안 | 이유 |
|---|---|---|
| Gateway는 **Java/Spring**, 추론은 Python 분리 | 전부 FastAPI | 모델 런타임(Python)과 업무 트랜잭션(JPA·검증·운영 도구)을 분리. 추론만 따로 스케일 |
| **트랜잭션 3분할** (PENDING 커밋 → 추론 → 결과 커밋) | 하나의 `@Transactional` | 느린 추론 동안 DB 커넥션을 쥐지 않는다. 아래 ④에서 이 결정 하나가 처리량 **~54배** 차이 |
| **`open-in-view: false`** (Spring Boot 기본값은 true) | 기본값 유지 | OSIV는 요청이 끝날 때까지 커넥션을 쥔다 → 3분할이 무력화된다(④ 실측) |
| 재시도는 **연결 실패·5xx만** | 모든 실패 재시도 | 4xx(깨진 이미지)는 다시 보내도 같다. 추론은 무상태라 재시도해도 중복 부작용이 없다 |
| 추론 실패는 **201 + FAILED** | 5xx 반환 | 접수 자체는 성공했고 기록이 남았다. 클라이언트가 재접수 여부를 판단한다 |
| 가상 스레드 **토글**(`VIRTUAL_THREADS`) | 고정 | 효과를 같은 이미지로 A/B 하려고 |
| Flyway + `ddl-auto: validate` | `update` | 스키마는 마이그레이션으로만 바뀐다 |
| DB 준비 대기 **initContainer** | 재시작에 맡김 | 첫 설치에서 Flyway 연결 실패로 재시작 2회 실측 → 0회 |

## ④ 성능 비교 (실측)

### 스레드 모델 × Open-In-View — 추론이 느릴 때 무엇이 천장인가

조건: 추론 서비스에 **500ms 지연 주입**(`EXTRA_LATENCY_MS`, VLM 트리아지 같은 느린 판정 경로를 흉내 — 실제 엣지 CNN은 4ms),
k6 closed model(같은 도커 네트워크), 단계당 30초, Tomcat 200 스레드, Hikari 풀 10. 원시값 `results/threads_bench.json`.

| 동시성 | 플랫폼 스레드 | **가상 스레드** | 플랫폼 + OSIV | 가상 + OSIV |
|---:|---|---|---|---|
| 50 | 98 req/s · p50 516ms | 97 · 522ms | **~19** · 2,566ms | ~19 · 2,574ms |
| 200 | 385 · 521ms | 381 · 529ms | ~20 · 10,235ms | ~20 · 10,274ms |
| 400 | 393 · **1,072ms** | **721 · 552ms** | ~20 · 20,432ms | ~20 · 20,040ms · 실패 0.71% |
| 800 | 406 · **2,187ms** | **1,081 · 729ms** | ~20 · 32,875ms | ~20 · 32,732ms · **실패 15.6%** |

(처리량 = 30초 창 요청 수 / 30. OSIV 열은 종료 대기 중 끝난 요청이 섞여 창 계산값이 21~46으로 부풀어서,
그 몫(≤ VUs)을 뺀 정상 상태 값 ~20을 적었다 — 이론 상한 `풀 10 ÷ 0.5s = 20`과 일치.)

1. **플랫폼 스레드의 천장은 Tomcat 200이다.** 200÷0.5s = 400 req/s에서 멈추고, 그 뒤 동시성은 대기열로
   가서 p50이 2배·4배로 늘어난다.
2. **가상 스레드는 그 천장을 없앤다** — 800 동시에서 처리량 **2.66배**(406→1,081), p50 2,187→729ms.
   다만 p50이 500→729ms로 오르기 시작한다. 다음 병목(DB 풀 10에 요청당 트랜잭션 2개)이 보이는 지점이다.
3. **OSIV가 켜져 있으면 스레드 모델은 무의미하다.** 요청이 느린 추론 동안 커넥션을 쥐어 처리량이
   **풀 크기÷지연 = 20 req/s**로 고정된다 — 동시성 50에서 이미 98→19(**−80%**).
4. **가상 스레드 + OSIV가 가장 나쁘다.** 플랫폼 스레드는 200개 스레드가 앞단 대기열 역할을 해서 풀 대기가
   30초를 넘지 않았다(실패 0). 가상 스레드는 그 방파제가 없어 800개가 전부 풀 앞에 선다 →
   `Connection is not available, request timed out after 30000ms (total=10, active=10, idle=0, waiting=389)`,
   **실패 15.6%**. "가상 스레드로 바꾸면 빨라진다"는 **풀을 쥐는 코드가 없을 때만** 참이다.

### e2e (실제 ONNX 추론, 지연 주입 없음)

샘플 24장 → 자동 채택 23 · 검토 큐 1 → 사람 확정 → 라인별 집계·Prometheus 카운터 일치.
깨진 이미지 → 추론 422 → **재시도 없이** `FAILED`(attempts=1). `results/e2e_smoke.json`.
지연 주입 없이 VU 10: 580 req/s · p50 16ms · 실패 0.

### K8s(minikube) — HPA는 반응했지만 처리량은 안 올랐다

Helm 설치(Gateway 1 고정 · 추론 HPA 1→6 @CPU 60%, 파드당 500m · PostgreSQL StatefulSet+PVC),
k6 64 VU × 6분, 지연 주입 없음. 원시값 `results/hpa_bench.json`.

| 시점 | HPA | 처리량 |
|---|---|---|
| 0~60s | 1개, 지표 미수집(metrics-server 지연) | ~116 req/s |
| 61s | CPU 138% → 목표 3개 | |
| 71~81s | 3개 Ready (**결정→Ready 약 20초**) | |
| 81~380s | 3개 유지, CPU 183%→61% | **~120 req/s — 그대로** |

**늘린 층이 병목이 아니었다.** 조건을 하나씩 바꿔 30초씩 다시 쟀다(`results/k8s_client_delay.json`):

| Gateway 조건 | 처리량 | 추론 호출 평균 |
|---|---:|---:|
| 가상 스레드 · CPU 1 | 161 | 45ms |
| 플랫폼 스레드 · CPU 1 | 160 | 105ms |
| 가상 스레드 · CPU 4 | 153 | 74ms |
| 플랫폼 스레드 · CPU 4 | 156 | 80ms |

스레드 모델도 Gateway CPU도 처리량을 못 움직인다. Gateway 메트릭으로 시간을 나누면 요청 평균 356ms 중
추론 79ms, **커넥션 획득 대기 106ms × 트랜잭션 2회**, 커넥션 점유 29ms/트랜잭션.
→ `풀 10 ÷ (2 × 29ms) ≈ 172 req/s`가 천장이고 실측 153~161과 맞는다. minikube PVC 위 PostgreSQL의
커밋 지연이 이 환경의 병목이다(compose에서는 같은 코드가 1,081 req/s까지 갔다).

**정직한 범위**: HPA 실측 구간에서 추론 호출 평균이 0.499s였는데, 이후 조건별 재측정에서는 45~105ms로
재현되지 않았다. 추론 1개 파드(CPU 500m)에 64 동시가 몰린 초반의 CFS 스로틀링, 또는 HTTP keep-alive로
연결이 처음 파드에 고정되는 효과가 후보지만 **확인하지 못했다.**
다음 단계: 요청당 트랜잭션을 2→1로 줄이는 설계(PENDING 기록을 비동기 큐로) 또는 DB 풀·커밋 경로 튜닝을 한 뒤에
HPA를 다시 재야 "파드를 늘리면 처리량이 오른다"를 말할 수 있다.

## ⑤ 교체 기록

- **OSIV 기본값(true) → false.** 트랜잭션을 나눠 놓고도 기본값 하나 때문에 효과가 0이 될 수 있음을
  ④ 3·4번으로 확인한 뒤 명시적으로 끄고, 설정을 환경변수로 노출해 회귀를 재현할 수 있게 했다.
- **재시작 의존 → initContainer.** 첫 Helm 설치에서 Gateway가 DB보다 먼저 떠 Flyway 연결 실패로 2회 재시작.
  `pg_isready` 대기 initContainer로 교체 후 새 설치에서 재시작 0회.
- **Page 직렬화** — Spring Data 경고(PageImpl 구조 불안정)를 보고 `VIA_DTO`로 교체해 API 응답 구조를 고정.

## ⑥ 에러 대처 기록 — 3초 꼬리 추적 (미해결, 범위를 좁힘)

모든 설정에서 p99가 약 3.1초였다. 원시 기록을 열어 보니 흩어진 꼬리가 아니라
**약 30초마다 그 순간 처리 중이던 요청 전부(50개면 50개, 200개면 200개)가 동시에 +2.5초** 되는 멈춤이었다.

| 후보 | 판정 | 근거 |
|---|---|---|
| 클라이언트 연결(SYN 재전송) | 기각 | k6 연결 단계 최대 49ms. 꼬리는 전부 응답 대기 구간 |
| 추론 호출 | 기각 | Gateway 타이머: 31,904건 중 0.63s 초과 1건 |
| JVM GC | 기각 | G1 최대 정지 13ms |
| WAL fsync | 기각 | `synchronous_commit=off`에서도 동일 — ABBA 4회: 2s 초과 598/600/600/602건 |
| 디스크 I/O | 기각 | PGDATA를 tmpfs(RAM)로 옮겨도 동일: disk 599·597 vs tmpfs 571 |
| **PostgreSQL COMMIT** | **여기서 멈춤** | `log_min_duration_statement` 로그: `COMMIT` 2,586~2,589ms, 여러 세션이 같은 시각 |

남은 후보는 PostgreSQL 내부의 전역 대기(락·백그라운드 작업) 또는 Docker Desktop VM 수준 정지다.
**모든 설정에 같은 크기로 걸리므로 ④의 처리량 비교는 유효하고, p99는 이 환경의 값으로만 읽는다.**
다음 단계: 멈춤 순간 `pg_stat_activity`의 wait_event를 0.1초 단위로 뜨기, 네이티브 리눅스 호스트에서 재현 여부.

## ⑦ 개발 순서

1. Java/Spring 서비스 층 경험이 없다는 점 확인 → InspectOps의 빈칸(서비스 층)과 겹친다는 판단으로 **새 파편이 아니라 플랫폼 층**으로 설계
2. 추론 서비스(FastAPI, HF Space와 같은 모델·전처리) → Gateway(도메인·트랜잭션 3분할·재시도) → 통합 테스트 9개
3. docker compose e2e(샘플 24장) → k6 부하 4설정×4단계
4. 3초 꼬리 추적(가설 5개 기각, COMMIT까지 좁힘)
5. Helm 차트 → minikube 설치(재시작 2회 발견 → initContainer) → HPA 실측
6. HPA가 늘었는데 처리량 불변 → 조건 분리 재측정 → 병목이 DB 커밋 층임을 확인(스케일 대상이 틀렸다)
