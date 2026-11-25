package com.example.contentlab.service;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.ExtendWith;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.mockito.InjectMocks;
import org.mockito.Mock;
import org.mockito.junit.jupiter.MockitoExtension;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.verifyNoInteractions;
import static org.mockito.Mockito.when;

@ExtendWith(MockitoExtension.class)
class MemberContentRatingServiceTests {
    @Mock JdbcTemplate jdbc;
    @InjectMocks MemberContentRatingService service;

    @Test
    void savesAndUpdatesRatingOnlyForExistingMemberScopedCatalogIdentity() {
        when(jdbc.queryForObject(anyString(), eq(Integer.class), any(), any())).thenReturn(1);
        when(jdbc.update(anyString(), any(), any(), any(), any())).thenReturn(1);

        assertEquals(4, service.save(12, "tv", 501, 4));
        assertEquals(2, service.save(12, "tv", 501, 2));
        verify(jdbc).update(org.mockito.ArgumentMatchers.contains("ON DUPLICATE KEY UPDATE rating"),
                eq(12L), eq(501L), eq("tv"), eq(4));
        verify(jdbc).update(org.mockito.ArgumentMatchers.contains("ON DUPLICATE KEY UPDATE rating"),
                eq(12L), eq(501L), eq("tv"), eq(2));
    }

    @Test
    void rejectsInvalidTypesIdsAndScoresBeforeDatabaseAccess() {
        assertThrows(ResponseStatusException.class, () -> service.save(12, "variety", 501, 4));
        assertThrows(ResponseStatusException.class, () -> service.save(12, "movie", 0, 4));
        assertThrows(ResponseStatusException.class, () -> service.save(12, "movie", 501, 0));
        assertThrows(ResponseStatusException.class, () -> service.save(12, "movie", 501, 6));
        verifyNoInteractions(jdbc);
    }
}
