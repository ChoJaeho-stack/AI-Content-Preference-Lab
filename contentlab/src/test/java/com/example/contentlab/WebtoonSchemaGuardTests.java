package com.example.contentlab;

import com.example.contentlab.repository.ContentRepository;
import com.example.contentlab.repository.RecommendationHistoryRepository;
import com.example.contentlab.service.AiRecommendationClient;
import com.example.contentlab.service.ContentService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;
import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

class WebtoonSchemaGuardTests {
    @Test
    void webtoonRecommendationReturnsUnavailableUntilMigrationExists() {
        var jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Integer.class))).thenReturn(0);
        var service = new ContentService(mock(ContentRepository.class),
                mock(RecommendationHistoryRepository.class), jdbc, mock(AiRecommendationClient.class));

        var error = assertThrows(ResponseStatusException.class,
                () -> service.recommend(Map.of("taste", "test", "contentType", "webtoon"), 11L));

        assertEquals(SERVICE_UNAVAILABLE, error.getStatusCode());
    }
}
