-- Apply only to a freshly created Content Lab schema. Select it before running.
-- Existing installations already own these tables and skip this file.

CREATE TABLE members (
    id BIGINT NOT NULL AUTO_INCREMENT,
    email VARCHAR(255) NOT NULL,
    password VARCHAR(255) NOT NULL,
    nickname VARCHAR(50) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uq_members_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE contents (
    id BIGINT NOT NULL,
    type VARCHAR(20) NOT NULL,
    title VARCHAR(255) NOT NULL,
    overview TEXT NULL,
    genre_ids JSON NULL,
    rating DOUBLE NULL,
    popularity DOUBLE NULL,
    ott JSON NULL,
    poster_url VARCHAR(2048) NULL,
    is_excluded BOOLEAN NOT NULL DEFAULT FALSE,
    PRIMARY KEY (id, type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE favorites (
    member_id BIGINT NOT NULL,
    content_id BIGINT NOT NULL,
    content_type VARCHAR(20) NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (member_id, content_id, content_type),
    CONSTRAINT fk_favorites_member FOREIGN KEY (member_id)
        REFERENCES members (id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE recommendation_history (
    id BIGINT NOT NULL AUTO_INCREMENT,
    member_id BIGINT NOT NULL,
    liked TEXT NULL,
    disliked TEXT NULL,
    preference VARCHAR(255) NULL,
    result JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    KEY ix_history_member_created (member_id, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
