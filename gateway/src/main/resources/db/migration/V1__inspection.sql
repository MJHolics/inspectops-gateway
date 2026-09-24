CREATE TABLE inspection (
    id             UUID PRIMARY KEY,
    line_id        VARCHAR(32)  NOT NULL,
    image_sha256   VARCHAR(64)  NOT NULL,
    status         VARCHAR(16)  NOT NULL,
    defect_class   VARCHAR(32),
    confidence     DOUBLE PRECISION,
    severity       VARCHAR(8),
    model_version  VARCHAR(64),
    inference_ms   DOUBLE PRECISION,
    attempts       INTEGER      NOT NULL DEFAULT 0,
    error_message  VARCHAR(500),
    reviewed_class VARCHAR(32),
    reviewer       VARCHAR(64),
    created_at     TIMESTAMP WITH TIME ZONE NOT NULL,
    completed_at   TIMESTAMP WITH TIME ZONE
);

-- 검토 큐 조회(상태별 오래된 순)와 라인별 집계
CREATE INDEX idx_inspection_status_created ON inspection (status, created_at);
CREATE INDEX idx_inspection_line_status ON inspection (line_id, status);
