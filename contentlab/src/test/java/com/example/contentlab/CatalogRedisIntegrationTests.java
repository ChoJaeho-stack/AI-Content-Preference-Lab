package com.example.contentlab;

import com.example.contentlab.service.CatalogCache;
import com.example.contentlab.service.ContentService;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.time.Duration;
import java.util.Arrays;
import java.util.Base64;
import java.util.Locale;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

@EnabledIfEnvironmentVariable(named = "CONTENTLAB_REDIS_INTEGRATION_TEST", matches = "true")
@SpringBootTest(properties = {
        "contentlab.cache.enabled=true",
        "spring.data.redis.host=127.0.0.1",
        "spring.data.redis.port=16379",
        "spring.data.redis.connect-timeout=3s",
        "spring.data.redis.timeout=3s",
        "spring.datasource.hikari.read-only=true",
        "spring.jpa.hibernate.ddl-auto=none",
        "spring.sql.init.mode=never"
})
class CatalogRedisIntegrationTests {
    @MockitoBean
    private JdbcTemplate jdbc;

    @Autowired
    private ContentService catalog;
    @Autowired
    private CatalogCache cache;
    @Autowired
    private StringRedisTemplate redis;

    @DynamicPropertySource
    static void testJwtKey(DynamicPropertyRegistry properties) {
        properties.add("JWT_SECRET", () -> Base64.getEncoder().encodeToString(new byte[32]));
    }

    @Test
    void measuresMvcResponsesAgainstMySqlAndRedisAndVerifiesActualExpiration() throws Exception {
        var item = catalog.getContents().stream().findFirst().orElseThrow();
        String detailPath = "/api/contents/" + item.type() + "/" + item.id();
        String detailKey = "contentlab:catalog:v1:detail:" + item.type() + ":" + item.id();
        Duration shortTtl = Duration.ofSeconds(2);
        var expiring = new CatalogCache(catalog, redis, true, shortTtl, shortTtl, shortTtl);
        assertEquals(item, expiring.detail(item.type(), item.id()));
        long remaining = redis.getExpire(detailKey, TimeUnit.MILLISECONDS);
        assertTrue(remaining > 0 && remaining <= shortTtl.toMillis());
        long deadline = System.nanoTime() + Duration.ofSeconds(5).toNanos();
        while (Boolean.TRUE.equals(redis.hasKey(detailKey)) && System.nanoTime() < deadline) {
            Thread.sleep(50);
        }
        assertEquals(Boolean.FALSE, redis.hasKey(detailKey));

        var uncached = new CatalogCache(catalog, redis, false, shortTtl, shortTtl, shortTtl);
        var withoutCache = mvc(uncached);
        var withCache = mvc(cache);
        for (String path : new String[]{"/api/contents", detailPath, detailPath + "/similar"}) {
            assertArrayEquals(response(withoutCache, path), response(withCache, path));
            for (int i = 0; i < 5; i++) {
                response(withoutCache, path);
                response(withCache, path);
            }
            long[] baseline = new long[31];
            long[] warm = new long[31];
            for (int i = 0; i < baseline.length; i++) {
                baseline[i] = elapsed(withoutCache, path);
                warm[i] = elapsed(withCache, path);
            }
            Arrays.sort(baseline);
            Arrays.sort(warm);
            System.out.printf(Locale.ROOT,
                    "REAL %s ms, disabled p50=%.3f p95=%.3f, warm p50=%.3f p95=%.3f%n",
                    path, millis(baseline[15]), millis(baseline[29]), millis(warm[15]), millis(warm[29]));
        }
        assertTrue(redis.getExpire("contentlab:catalog:v1:list:all") > 0);
        assertTrue(redis.getExpire(detailKey) > 0);
        assertTrue(redis.getExpire("contentlab:catalog:v1:similar:" + item.type() + ":" + item.id()) > 0);
    }

    private MockMvc mvc(CatalogCache catalogCache) {
        return MockMvcBuilders.standaloneSetup(new ContentController(catalog, catalogCache)).build();
    }

    private static byte[] response(MockMvc client, String path) throws Exception {
        return client.perform(get(path)).andExpect(status().isOk())
                .andReturn().getResponse().getContentAsByteArray();
    }

    private static long elapsed(MockMvc client, String path) throws Exception {
        long start = System.nanoTime();
        response(client, path);
        return System.nanoTime() - start;
    }

    private static double millis(long nanos) {
        return nanos / 1_000_000.0;
    }
}
