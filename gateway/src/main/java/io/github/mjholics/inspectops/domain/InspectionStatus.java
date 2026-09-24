package io.github.mjholics.inspectops.domain;

public enum InspectionStatus {
    /** 접수됨, 추론 결과 대기 */
    PENDING,
    /** confidence ≥ 임계값 — 자동 판정 채택 */
    AUTO_ACCEPTED,
    /** confidence < 임계값 — 사람 검토 큐 */
    NEEDS_REVIEW,
    /** 사람이 검토해 최종 라벨을 확정 */
    REVIEWED,
    /** 추론 서비스 실패·타임아웃 — 판정 없음 (지어내지 않는다) */
    FAILED
}
