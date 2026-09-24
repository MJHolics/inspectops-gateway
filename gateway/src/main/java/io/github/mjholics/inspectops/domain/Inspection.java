package io.github.mjholics.inspectops.domain;

import jakarta.persistence.Column;
import jakarta.persistence.Entity;
import jakarta.persistence.EnumType;
import jakarta.persistence.Enumerated;
import jakarta.persistence.Id;
import jakarta.persistence.Table;

import java.time.Instant;
import java.util.UUID;

@Entity
@Table(name = "inspection")
public class Inspection {

    @Id
    private UUID id;

    @Column(name = "line_id", nullable = false, length = 32)
    private String lineId;

    @Column(name = "image_sha256", nullable = false, length = 64)
    private String imageSha256;

    @Enumerated(EnumType.STRING)
    @Column(nullable = false, length = 16)
    private InspectionStatus status;

    @Column(name = "defect_class", length = 32)
    private String defectClass;

    private Double confidence;

    @Column(length = 8)
    private String severity;

    @Column(name = "model_version", length = 64)
    private String modelVersion;

    @Column(name = "inference_ms")
    private Double inferenceMs;

    @Column(name = "attempts", nullable = false)
    private int attempts;

    @Column(name = "error_message", length = 500)
    private String errorMessage;

    @Column(name = "reviewed_class", length = 32)
    private String reviewedClass;

    @Column(name = "reviewer", length = 64)
    private String reviewer;

    @Column(name = "created_at", nullable = false)
    private Instant createdAt;

    @Column(name = "completed_at")
    private Instant completedAt;

    protected Inspection() {
    }

    public static Inspection pending(String lineId, String imageSha256, Instant now) {
        Inspection i = new Inspection();
        i.id = UUID.randomUUID();
        i.lineId = lineId;
        i.imageSha256 = imageSha256;
        i.status = InspectionStatus.PENDING;
        i.createdAt = now;
        return i;
    }

    public void complete(InferenceResult r, int attempts, double reviewThreshold, Instant now) {
        requireStatus(InspectionStatus.PENDING);
        this.defectClass = r.defectClass();
        this.confidence = r.confidence();
        this.severity = r.severity();
        this.modelVersion = r.modelVersion();
        this.inferenceMs = r.modelMs();
        this.attempts = attempts;
        this.status = r.confidence() >= reviewThreshold
                ? InspectionStatus.AUTO_ACCEPTED
                : InspectionStatus.NEEDS_REVIEW;
        this.completedAt = now;
    }

    public void fail(String message, int attempts, Instant now) {
        requireStatus(InspectionStatus.PENDING);
        this.status = InspectionStatus.FAILED;
        this.errorMessage = message.length() > 500 ? message.substring(0, 500) : message;
        this.attempts = attempts;
        this.completedAt = now;
    }

    public void review(String finalClass, String reviewer) {
        requireStatus(InspectionStatus.NEEDS_REVIEW);
        this.reviewedClass = finalClass;
        this.reviewer = reviewer;
        this.status = InspectionStatus.REVIEWED;
    }

    private void requireStatus(InspectionStatus expected) {
        if (status != expected) {
            throw new IllegalStateException("상태 전이 불가: " + status + " (필요: " + expected + ")");
        }
    }

    public UUID getId() { return id; }
    public String getLineId() { return lineId; }
    public String getImageSha256() { return imageSha256; }
    public InspectionStatus getStatus() { return status; }
    public String getDefectClass() { return defectClass; }
    public Double getConfidence() { return confidence; }
    public String getSeverity() { return severity; }
    public String getModelVersion() { return modelVersion; }
    public Double getInferenceMs() { return inferenceMs; }
    public int getAttempts() { return attempts; }
    public String getErrorMessage() { return errorMessage; }
    public String getReviewedClass() { return reviewedClass; }
    public String getReviewer() { return reviewer; }
    public Instant getCreatedAt() { return createdAt; }
    public Instant getCompletedAt() { return completedAt; }
}
