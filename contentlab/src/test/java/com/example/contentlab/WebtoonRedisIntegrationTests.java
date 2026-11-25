package com.example.contentlab;

import com.example.contentlab.dto.WebtoonResponse;
import com.example.contentlab.service.CatalogCache;
import com.example.contentlab.service.ContentService;
import com.example.contentlab.service.WebtoonCatalogService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.Duration;
import java.util.Arrays;
import java.util.List;
import java.util.Locale;
import java.util.UUID;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@EnabledIfEnvironmentVariable(named = "CONTENTLAB_WEBTOON_REDIS_TEST", matches = "true")
class WebtoonRedisIntegrationTests {
    private static final String PREFIX = "contentlab:catalog:v1:webtoon:";
    private static final String GENERATION = PREFIX + "generation";
    private static final String URL = "/api/webtoons";
    private static final Duration TTL = Duration.ofSeconds(60);
    private static final int SAMPLE_COUNT = 31;

    @Test
    void verifiesLiveRedisAndMeasuresWebtoonApiWithSimulatedJdbc() throws Exception {
        var config = new RedisStandaloneConfiguration("127.0.0.1", 16379);
        config.setDatabase(12);
        var connection = new LettuceConnectionFactory(config,
                LettuceClientConfiguration.builder().commandTimeout(Duration.ofSeconds(3)).build());
        connection.afterPropertiesSet();
        try {
            var redis = new StringRedisTemplate(connection);
            assertNull(redis.opsForValue().get(GENERATION), "Use a fresh, dedicated Redis instance");
            var title = new AtomicReference<>("Original title");
            var queries = new AtomicInteger();
            var jdbc = simulatedJdbc(title, queries);
            var uncached = mvc(redis, jdbc, false, TTL);
            var cached = mvc(redis, jdbc, true, TTL);

            byte[] original = response(uncached, URL);
            assertArrayEquals(original, response(cached, URL));
            assertArrayEquals(original, response(cached, URL));
            assertEquals(2, queries.get());

            String previousGeneration = redis.opsForValue().get(GENERATION);
            assertNotNull(previousGeneration);
            String previousKey = PREFIX + "list:" + previousGeneration + ":1:20:::";
            long remaining = redis.getExpire(previousKey, TimeUnit.MILLISECONDS);
            assertTrue(remaining > 0 && remaining <= TTL.toMillis());

            title.set("Updated title");
            assertArrayEquals(original, response(cached, URL));
            redis.opsForValue().set(GENERATION, UUID.randomUUID().toString());
            byte[] updated = response(uncached, URL);
            assertFalse(Arrays.equals(original, updated));
            assertArrayEquals(updated, response(cached, URL));
            assertEquals(4, queries.get());
            assertTrue(redis.hasKey(previousKey));

            measure(uncached, cached, queries);

            var expiring = mvc(redis, jdbc, true, Duration.ofSeconds(1));
            response(expiring, URL + "?page=2");
            String expiringKey = PREFIX + "list:" + redis.opsForValue().get(GENERATION) + ":2:20:::";
            assertTrue(redis.hasKey(expiringKey));
            long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
            while (Boolean.TRUE.equals(redis.hasKey(expiringKey)) && System.nanoTime() < deadline) {
                Thread.sleep(25);
            }
            assertFalse(redis.hasKey(expiringKey));
        } finally {
            connection.destroy();
        }
    }

    private static JdbcTemplate simulatedJdbc(AtomicReference<String> title, AtomicInteger queries) {
        var jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(anyString(), eq(Integer.class))).thenReturn(5);
        when(jdbc.query(anyString(), org.mockito.ArgumentMatchers.<RowMapper<WebtoonResponse>>any(),
                any(Object[].class))).thenAnswer(invocation -> {
                    queries.incrementAndGet();
                    Thread.sleep(10);
                    return List.of(new WebtoonResponse(42L, "webtoon", title.get(), null, null, null,
                            "fixture", "42", "fixture", null, null, null, null, null, null, "ongoing"));
                });
        return jdbc;
    }

    private static MockMvc mvc(StringRedisTemplate redis, JdbcTemplate jdbc, boolean enabled, Duration ttl) {
        var cache = new CatalogCache(mock(ContentService.class), redis, enabled, ttl, ttl, ttl);
        var service = new WebtoonCatalogService(jdbc, cache, ttl);
        return MockMvcBuilders.standaloneSetup(new WebtoonController(service)).build();
    }

    private static void measure(MockMvc uncached, MockMvc cached, AtomicInteger queries) throws Exception {
        for (int i = 0; i < 5; i++) {
            response(uncached, URL);
            response(cached, URL);
        }
        int before = queries.get();
        long[] baseline = new long[SAMPLE_COUNT];
        long[] warm = new long[SAMPLE_COUNT];
        for (int i = 0; i < SAMPLE_COUNT; i++) {
            baseline[i] = elapsed(uncached);
            warm[i] = elapsed(cached);
        }
        assertEquals(SAMPLE_COUNT, queries.get() - before);
        Arrays.sort(baseline);
        Arrays.sort(warm);
        System.out.printf(Locale.ROOT,
                "WEBTOON live Redis + simulated JDBC (10ms) MockMvc ms: uncached p50=%.3f p95=%.3f; hit p50=%.3f p95=%.3f%n",
                millis(baseline[15]), millis(baseline[29]), millis(warm[15]), millis(warm[29]));
    }

    private static byte[] response(MockMvc mvc, String url) throws Exception {
        return mvc.perform(get(url)).andExpect(status().isOk()).andReturn().getResponse().getContentAsByteArray();
    }

    private static long elapsed(MockMvc mvc) throws Exception {
        long start = System.nanoTime();
        response(mvc, URL);
        return System.nanoTime() - start;
    }

    private static double millis(long nanos) {
        return nanos / 1_000_000.0;
    }
}
