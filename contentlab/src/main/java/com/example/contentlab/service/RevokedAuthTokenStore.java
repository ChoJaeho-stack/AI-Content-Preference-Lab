package com.example.contentlab.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.HexFormat;

/** Stores only token digests so a logged-out JWT can be rejected immediately. */
@Service
public class RevokedAuthTokenStore {
    private final JdbcTemplate jdbc;

    public RevokedAuthTokenStore(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public boolean isRevoked(String token) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*) FROM revoked_auth_tokens
                WHERE token_hash=? AND expires_at>CURRENT_TIMESTAMP(6)
                """, Integer.class, digest(token));
        return count != null && count > 0;
    }

    @Transactional
    public void revoke(String token, Instant expiresAt) {
        if (token == null || token.isBlank() || expiresAt == null || !expiresAt.isAfter(Instant.now())) {
            return;
        }
        jdbc.update("DELETE FROM revoked_auth_tokens WHERE expires_at<=CURRENT_TIMESTAMP(6)");
        jdbc.update("""
                INSERT INTO revoked_auth_tokens(token_hash, expires_at) VALUES (?, ?)
                ON DUPLICATE KEY UPDATE expires_at=GREATEST(expires_at, VALUES(expires_at))
                """, digest(token), Timestamp.from(expiresAt));
    }

    static String digest(String token) {
        try {
            byte[] bytes = MessageDigest.getInstance("SHA-256")
                    .digest(token.getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        } catch (NoSuchAlgorithmException impossible) {
            throw new IllegalStateException("SHA-256 is unavailable", impossible);
        }
    }
}
