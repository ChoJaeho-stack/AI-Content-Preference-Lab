package com.example.contentlab.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.mockito.ArgumentCaptor;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;
import org.springframework.jdbc.core.JdbcTemplate;

import java.sql.Timestamp;
import java.time.Instant;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotEquals;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class RevokedAuthTokenStoreTests {
    @Mock JdbcTemplate jdbc;
    @InjectMocks RevokedAuthTokenStore store;

    @Test
    void storesOnlySha256AndChecksTheDigest() {
        String token = "signed.jwt.value";
        when(jdbc.update(anyString())).thenReturn(0);
        when(jdbc.update(anyString(), any(), any(Timestamp.class))).thenReturn(1);
        ArgumentCaptor<String> digest = ArgumentCaptor.forClass(String.class);

        store.revoke(token, Instant.now().plusSeconds(600));
        verify(jdbc).update(eq("DELETE FROM revoked_auth_tokens WHERE expires_at<=CURRENT_TIMESTAMP(6)"));
        verify(jdbc).update(org.mockito.ArgumentMatchers.contains("INSERT INTO revoked_auth_tokens"),
                digest.capture(), any(Timestamp.class));
        assertEquals(64, digest.getValue().length());
        assertNotEquals(token, digest.getValue());

        when(jdbc.queryForObject(anyString(), eq(Integer.class), any())).thenReturn(1);
        assertEquals(true, store.isRevoked(token));
        verify(jdbc).queryForObject(org.mockito.ArgumentMatchers.contains("token_hash=?"),
                eq(Integer.class), eq(digest.getValue()));
    }
}
