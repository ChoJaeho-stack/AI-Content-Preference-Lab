-- Additive migration. Keeps the existing webtoon preference feedback table intact.
CREATE TABLE IF NOT EXISTS member_content_ratings (
    member_id BIGINT NOT NULL,
    content_id BIGINT NOT NULL,
    content_type VARCHAR(20) NOT NULL,
    rating TINYINT UNSIGNED NOT NULL,
    created_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    updated_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
        ON UPDATE CURRENT_TIMESTAMP(6),
    PRIMARY KEY (member_id, content_id, content_type),
    KEY ix_member_content_ratings_content (content_type, content_id),
    CONSTRAINT ck_member_content_ratings_value CHECK (rating BETWEEN 1 AND 5),
    CONSTRAINT fk_member_content_ratings_member
        FOREIGN KEY (member_id) REFERENCES members (id)
        ON UPDATE RESTRICT ON DELETE CASCADE,
    CONSTRAINT fk_member_content_ratings_content
        FOREIGN KEY (content_id, content_type) REFERENCES contents (id, type)
        ON UPDATE RESTRICT ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Store only a SHA-256 digest, never the bearer JWT itself.
CREATE TABLE IF NOT EXISTS revoked_auth_tokens (
    token_hash CHAR(64) CHARACTER SET ascii COLLATE ascii_bin NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    revoked_at TIMESTAMP(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
    PRIMARY KEY (token_hash),
    KEY ix_revoked_auth_tokens_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
