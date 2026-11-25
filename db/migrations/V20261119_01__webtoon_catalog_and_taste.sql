-- Original additive schema. A read-only inspection of the current local MySQL
-- found these tables and the original source-identity foreign key already
-- present; other environments must be inspected independently.
-- content_external_ids is an optional verified provider-ID mapping. A source
-- may have verified catalog metadata before it exposes a stable external ID.

CREATE TABLE content_external_ids (
    provider_code VARCHAR(80) NOT NULL,
    external_id VARCHAR(191) CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_bin NOT NULL,
    content_type VARCHAR(20) NOT NULL,
    content_id BIGINT NOT NULL,
    source_url VARCHAR(2048) NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (provider_code, external_id),
    UNIQUE KEY uq_external_identity_content (provider_code, content_type, content_id),
    KEY ix_external_identity_internal (content_id, content_type),
    CONSTRAINT fk_external_identity_content
        FOREIGN KEY (content_id, content_type)
        REFERENCES contents (id, type)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE webtoon_metadata (
    content_id BIGINT NOT NULL,
    content_type VARCHAR(20) NOT NULL DEFAULT 'webtoon',
    service_platform VARCHAR(80) NOT NULL,
    official_url VARCHAR(2048) NULL,
    authors JSON NULL,
    genre_tags JSON NULL,
    story_tags JSON NULL,
    mood_tags JSON NULL,
    pacing VARCHAR(40) NULL,
    serial_status VARCHAR(40) NULL,
    source_provider VARCHAR(80) NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (content_id, content_type),
    KEY ix_webtoon_source_identity (source_provider, content_type, content_id),
    CONSTRAINT ck_webtoon_metadata_type CHECK (content_type = 'webtoon'),
    CONSTRAINT fk_webtoon_metadata_content
        FOREIGN KEY (content_id, content_type)
        REFERENCES contents (id, type)
        ON UPDATE RESTRICT ON DELETE RESTRICT
    -- source_provider records provenance; it is not an external identifier.
    -- Do not require an external-ID mapping for internally identified records.
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE member_taste_surveys (
    member_id BIGINT NOT NULL,
    survey JSON NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (member_id),
    CONSTRAINT fk_taste_survey_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE member_content_feedback (
    member_id BIGINT NOT NULL,
    content_id BIGINT NOT NULL,
    content_type VARCHAR(20) NOT NULL,
    rating TINYINT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (member_id, content_id, content_type),
    KEY ix_content_feedback_content (content_id, content_type),
    CONSTRAINT ck_content_feedback_rating CHECK (rating IN (-1, 0, 1)),
    CONSTRAINT fk_content_feedback_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_content_feedback_content
        FOREIGN KEY (content_id, content_type)
        REFERENCES contents (id, type)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE member_taste_profiles (
    member_id BIGINT NOT NULL,
    profile JSON NOT NULL,
    revision INT NOT NULL DEFAULT 1,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (member_id),
    CONSTRAINT fk_taste_profile_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
