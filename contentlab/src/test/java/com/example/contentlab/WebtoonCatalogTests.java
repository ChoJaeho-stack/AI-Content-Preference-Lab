package com.example.contentlab;

import com.example.contentlab.dto.WebtoonResponse;
import com.example.contentlab.service.CatalogCache;
import com.example.contentlab.service.ContentService;
import com.example.contentlab.service.WebtoonCatalogService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

class WebtoonCatalogTests {
    private static final String PREFIX = "contentlab:catalog:v1:webtoon:";
    private static final String GENERATION = PREFIX + "generation";
    private static final Duration TTL = Duration.ofSeconds(45);
    private static final WebtoonResponse WEBTOON = new WebtoonResponse(42L, "webtoon", "Fixture", null,
            null, null, "fixture", "42", "fixture", null, null, null, null, null, null, "ongoing");
    private final JdbcTemplate jdbc = mock(JdbcTemplate.class);
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    @SuppressWarnings("unchecked")
    private final ValueOperations<String, String> values = mock(ValueOperations.class);
    private final Map<String, String> entries = new HashMap<>();

    @BeforeEach
    void configureMocks() {
        when(jdbc.queryForObject(anyString(), eq(Integer.class))).thenReturn(5);
        when(jdbc.query(anyString(), org.mockito.ArgumentMatchers.<RowMapper<WebtoonResponse>>any(),
                any(Object[].class))).thenReturn(List.of(WEBTOON));
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenAnswer(call -> entries.get(call.getArgument(0)));
        when(values.setIfAbsent(eq(GENERATION), anyString())).thenAnswer(
                call -> entries.putIfAbsent(call.getArgument(0), call.getArgument(1)) == null);
        doAnswer(call -> {
            entries.put(call.getArgument(0), call.getArgument(1));
            return null;
        }).when(values).set(startsWith(PREFIX + "list:"), anyString(), eq(TTL));
    }

    @Test
    void defaultPagePreservesResponseArrayAndInvalidPagesDoNotReachDatabase() throws Exception {
        var mvc = MockMvcBuilders.standaloneSetup(new WebtoonController(service(false))).build();
        mvc.perform(get("/api/webtoons"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$[0].id").value(42));
        for (var invalid : List.of(Map.entry("page", "0"), Map.entry("page", "101"),
                Map.entry("size", "0"), Map.entry("size", "51"), Map.entry("page", "wrong"))) {
            mvc.perform(get("/api/webtoons").param(invalid.getKey(), invalid.getValue()))
                    .andExpect(status().isBadRequest());
        }
        verify(jdbc).query(contains("ORDER BY c.id LIMIT ? OFFSET ?"), any(RowMapper.class), eq(20), eq(0));
        verifyNoInteractions(redis);
    }

    @Test
    void combinedFiltersBindNormalizedValuesAndTreatWildcardsLiterally() {
        assertEquals(List.of(WEBTOON), service(false).search(" Ab%_! ", " Fantasy ", " ONGOING ", 100, 50));
        verify(jdbc).query(argThat(sql -> sql.contains("JSON_TABLE(w.authors")
                        && sql.contains("JSON_TABLE(w.genre_tags")
                        && sql.contains("LOWER(TRIM(w.serial_status)) = ?")
                        && sql.endsWith("ORDER BY c.id LIMIT ? OFFSET ?")),
                any(RowMapper.class), eq("%ab!%!_!!%"), eq("%ab!%!_!!%"),
                eq("fantasy"), eq("ongoing"), eq(50), eq(4950));
    }

    @Test
    void pageSizeAndEachNormalizedFilterHaveTheirOwnCacheEntry() {
        var service = service(true);
        assertEquals(List.of(WEBTOON), service.search(" Title ", " Fantasy ", " ONGOING ", 1, 20));
        assertEquals(List.of(WEBTOON), service.search("title", "fantasy", "ongoing", 1, 20));
        service.search("title", "fantasy", "ongoing", 2, 20);
        service.search("title", "fantasy", "ongoing", 1, 10);
        service.search("other", "fantasy", "ongoing", 1, 20);
        service.search("title", "romance", "ongoing", 1, 20);
        service.search("title", "fantasy", "completed", 1, 20);

        verify(jdbc, times(6)).query(anyString(), any(RowMapper.class), any(Object[].class));
        verify(values, times(6)).set(startsWith(PREFIX + "list:"), anyString(), eq(TTL));
        assertEquals(7, entries.size());
    }

    @Test
    void generationChangeRefreshesEveryCachedPageAndFilter() {
        var service = service(true);
        service.search(null, null, null, 1, 20);
        service.search("title", "fantasy", null, 2, 20);
        entries.put(GENERATION, "next-generation");
        service.search(null, null, null, 1, 20);
        service.search("title", "fantasy", null, 2, 20);

        verify(values, times(2)).set(startsWith(PREFIX + "list:next-generation:"), anyString(), eq(TTL));
        verify(jdbc, times(4)).query(anyString(), any(RowMapper.class), any(Object[].class));
    }

    @Test
    void redisReadAndWriteFailuresFallBackAndSchemaErrorsDoNotGetCached() {
        var service = service(true);
        when(values.get(GENERATION)).thenThrow(new RedisConnectionFailureException("offline"))
                .thenReturn("generation");
        doThrow(new RedisConnectionFailureException("offline")).when(values)
                .set(startsWith(PREFIX + "list:"), anyString(), eq(TTL));
        assertEquals(List.of(WEBTOON), service.search(null, null, null, 1, 20));
        assertEquals(List.of(WEBTOON), service.search(null, null, null, 1, 20));

        when(jdbc.queryForObject(anyString(), eq(Integer.class))).thenReturn(0);
        var error = assertThrows(ResponseStatusException.class, () -> service.search(null, null, null, 1, 20));
        assertEquals(503, error.getStatusCode().value());
        verify(jdbc, times(2)).query(anyString(), any(RowMapper.class), any(Object[].class));
        verify(values).set(startsWith(PREFIX + "list:"), anyString(), eq(TTL));
    }

    private WebtoonCatalogService service(boolean enabled) {
        var cache = new CatalogCache(mock(ContentService.class), redis, enabled, TTL, TTL, TTL);
        return new WebtoonCatalogService(jdbc, cache, TTL);
    }
}
