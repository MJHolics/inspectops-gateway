package io.github.mjholics.inspectops.api;

import io.github.mjholics.inspectops.domain.Inspection;
import io.github.mjholics.inspectops.domain.InspectionStatus;

import java.time.Instant;
import java.util.UUID;

public record InspectionView(
        UUID id,
        String lineId,
        InspectionStatus status,
        String defectClass,
        Double confidence,
        String severity,
        String modelVersion,
        Double inferenceMs,
        int attempts,
        String errorMessage,
        String reviewedClass,
        String reviewer,
        Instant createdAt,
        Instant completedAt
) {
    public static InspectionView of(Inspection i) {
        return new InspectionView(i.getId(), i.getLineId(), i.getStatus(), i.getDefectClass(),
                i.getConfidence(), i.getSeverity(), i.getModelVersion(), i.getInferenceMs(),
                i.getAttempts(), i.getErrorMessage(), i.getReviewedClass(), i.getReviewer(),
                i.getCreatedAt(), i.getCompletedAt());
    }
}
