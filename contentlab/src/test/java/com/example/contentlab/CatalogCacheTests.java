package com.example.contentlab;

import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.service.CatalogCache;
import com.example.contentlab.service.ContentService;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.RedisConnectionFailureException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.concurrent.locks.LockSupport;
import java.util.function.Supplier;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.http.HttpStatus.NOT_FOUND;

class CatalogCacheTests {
    private static final String PREFIX = "contentlab:catalog:v1:";
    private static final Duration LIST_TTL = Duration.ofSeconds(60);
    private static final Duration DETAIL_TTL = Duration.ofMinutes(5);
    private static final Duration SIMILAR_TTL = Duration.ofMinutes(2);
    private final ContentService catalog = mock(ContentService.class);
    private final StringRedisTemplate redis = mock(StringRedisTemplate.class);
    private final Map<String, String> entries = new HashMap<>();
    private final ContentResponse movie = content("movie");
    private final ContentResponse tv = content("tv");
    private ValueOperations<String, String> values;
    private ContentController controller;

    @BeforeEach
    @SuppressWarnings("unchecked")
    void setUp() {
        values = mock(ValueOperations.class);
        when(redis.opsForValue()).thenReturn(values);
        when(values.get(anyString())).thenAnswer(call -> entries.get(call.getArgument(0)));
        doAnswer(call -> {
            entries.put(call.getArgument(0), call.getArgument(1));
            return null;
        }).when(values).set(anyString(), anyString(), any(Duration.class));
        controller = controller(true);
    }

    @Test
    void cachesEachRouteWithItsTtlAndSeparatesTypesAndListFilters() {
        when(catalog.getContents()).thenReturn(List.of(movie, tv));
        when(catalog.getContentsByType("movie")).thenReturn(List.of(movie));
        when(catalog.getContentDetail("movie", 7L)).thenReturn(movie);
        when(catalog.getContentDetail("tv", 7L)).thenReturn(tv);
        when(catalog.getSimilarContents("movie", 7L)).thenReturn(List.of(tv));

        assertEquals(List.of(movie, tv), controller.getContents(null));
        assertEquals(List.of(movie, tv), controller.getContents(" "));
        assertEquals(List.of(movie), controller.getContents("movie"));
        assertEquals(List.of(movie), controller.getContents("movie"));
        assertEquals(movie, controller.getContentDetail("movie", 7L));
        assertEquals(movie, controller.getContentDetail("movie", 7L));
        assertEquals(tv, controller.getContentDetail("tv", 7L));
        assertEquals(List.of(tv), controller.getSimilarContents("movie", 7L));
        assertEquals(List.of(tv), controller.getSimilarContents("movie", 7L));

        verify(catalog).getContents();
        verify(catalog).getContentsByType("movie");
        verify(catalog).getContentDetail("movie", 7L);
        verify(catalog).getContentDetail("tv", 7L);
        verify(catalog).getSimilarContents("movie", 7L);
        verify(values).set(eq(PREFIX + "list:all"), anyString(), eq(LIST_TTL));
        verify(values).set(eq(PREFIX + "list:type:movie"), anyString(), eq(LIST_TTL));
        verify(values).set(eq(PREFIX + "detail:movie:7"), anyString(), eq(DETAIL_TTL));
        verify(values).set(eq(PREFIX + "similar:movie:7"), anyString(), eq(SIMILAR_TTL));
    }

    @Test
    void cacheReadFailureFallsBackToCatalogWithoutWaitingForASecondRedisCall() {
        when(values.get(anyString())).thenThrow(new RedisConnectionFailureException("offline"));
        when(catalog.getContents()).thenReturn(List.of(movie));
        when(catalog.getContentDetail("movie", 7L)).thenReturn(movie);
        when(catalog.getSimilarContents("movie", 7L)).thenReturn(List.of(tv));

        assertEquals(List.of(movie), controller.getContents(null));
        assertEquals(movie, controller.getContentDetail("movie", 7L));
        assertEquals(List.of(tv), controller.getSimilarContents("movie", 7L));
        verify(values, never()).set(anyString(), anyString(), any(Duration.class));
    }

    @Test
    void badCacheEntryAndWriteFailureStillReturnCatalogResult() {
        entries.put(PREFIX + "detail:movie:7", "{");
        when(catalog.getContentDetail("movie", 7L)).thenReturn(movie);
        doThrow(new RedisConnectionFailureException("offline"))
                .when(values).set(anyString(), anyString(), any(Duration.class));

        assertEquals(movie, controller.getContentDetail("movie", 7L));
        verify(catalog).getContentDetail("movie", 7L);
    }

    @Test
    void preservesNotFoundAndDoesNotCacheIt() {
        when(catalog.getContentDetail("movie", 7L)).thenThrow(new ResponseStatusException(NOT_FOUND));
        var error = assertThrows(ResponseStatusException.class,
                () -> controller.getContentDetail("movie", 7L));
        assertEquals(NOT_FOUND, error.getStatusCode());
        verify(values, never()).set(anyString(), anyString(), any(Duration.class));
    }

    @Test
    void disabledCacheDoesNotContactRedis() {
        when(catalog.getContents()).thenReturn(List.of(movie));
        assertEquals(List.of(movie), controller(false).getContents(null));
        verifyNoInteractions(redis);
    }

    @Test
    void comparesDisabledCacheWithWarmCacheUsingSimulatedCatalogLatency() {
        when(catalog.getContents()).thenAnswer(call -> simulatedDatabase(List.of(movie)));
        when(catalog.getContentDetail("movie", 7L)).thenAnswer(call -> simulatedDatabase(movie));
        when(catalog.getSimilarContents("movie", 7L)).thenAnswer(call -> simulatedDatabase(List.of(tv)));
        var uncached = controller(false);

        compare("list", () -> uncached.getContents(null), () -> controller.getContents(null));
        compare("detail", () -> uncached.getContentDetail("movie", 7L),
                () -> controller.getContentDetail("movie", 7L));
        compare("similar", () -> uncached.getSimilarContents("movie", 7L),
                () -> controller.getSimilarContents("movie", 7L));
    }

    private ContentController controller(boolean enabled) {
        return new ContentController(catalog, new CatalogCache(catalog, redis, enabled,
                LIST_TTL, DETAIL_TTL, SIMILAR_TTL));
    }

    private static ContentResponse content(String type) {
        return new ContentResponse(7L, type, "Title", "Overview", "[35]", 8.0, 9.0, "[]", null);
    }

    private static <T> T simulatedDatabase(T value) {
        LockSupport.parkNanos(Duration.ofMillis(10).toNanos());
        return value;
    }

    private static void compare(String route, Supplier<?> uncached, Supplier<?> cached) {
        assertEquals(uncached.get(), cached.get());
        for (int i = 0; i < 10; i++) {
            cached.get();
        }
        System.out.printf(Locale.ROOT, "SIMULATED %s p50 ms, disabled=%.3f warm=%.3f%n",
                route, medianMillis(uncached), medianMillis(cached));
    }

    private static double medianMillis(Supplier<?> request) {
        long[] samples = new long[31];
        for (int i = 0; i < samples.length; i++) {
            long start = System.nanoTime();
            request.get();
            samples[i] = System.nanoTime() - start;
        }
        Arrays.sort(samples);
        return samples[samples.length / 2] / 1_000_000.0;
    }
}
