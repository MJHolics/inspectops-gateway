package io.github.mjholics.inspectops.domain;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import com.fasterxml.jackson.annotation.JsonProperty;

/** 추론 서비스 `/v1/inspect` 응답 중 Gateway가 쓰는 필드. */
@JsonIgnoreProperties(ignoreUnknown = true)
public record InferenceResult(
        @JsonProperty("defect_class") String defectClass,
        double confidence,
        String severity,
        @JsonProperty("model_version") String modelVersion,
        @JsonProperty("model_ms") double modelMs
) {
}
