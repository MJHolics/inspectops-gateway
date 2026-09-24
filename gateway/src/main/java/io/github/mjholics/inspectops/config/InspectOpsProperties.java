package io.github.mjholics.inspectops.config;

import jakarta.validation.constraints.DecimalMax;
import jakarta.validation.constraints.DecimalMin;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.validation.annotation.Validated;

import java.time.Duration;

/**
 * Gateway 운영 파라미터.
 *
 * @param inferenceUrl     추론 서비스 base URL
 * @param connectTimeout   추론 서비스 연결 타임아웃
 * @param readTimeout      추론 응답 대기 상한 — 넘으면 FAILED로 기록하고 판정을 지어내지 않는다
 * @param maxAttempts      연결 실패·5xx에 한해 재시도 포함 총 시도 횟수 (4xx는 재시도하지 않는다)
 * @param reviewThreshold  confidence가 이 값 미만이면 사람 검토 큐로 (HF Space 데모와 같은 0.80)
 */
@Validated
@ConfigurationProperties(prefix = "inspectops")
public record InspectOpsProperties(
        @NotBlank String inferenceUrl,
        Duration connectTimeout,
        Duration readTimeout,
        @Min(1) int maxAttempts,
        @DecimalMin("0.0") @DecimalMax("1.0") double reviewThreshold
) {
}
