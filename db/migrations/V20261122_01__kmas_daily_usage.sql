-- Additive support for approval-gated KMAS sync. Apply only in an isolated
-- webtoon catalog schema after reviewing the deployment-specific migration plan.
CREATE TABLE kmas_api_daily_usage (
    usage_date DATE NOT NULL,
    request_count INT NOT NULL DEFAULT 0,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (usage_date),
    CONSTRAINT ck_kmas_daily_request_count CHECK (request_count BETWEEN 0 AND 1000)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
