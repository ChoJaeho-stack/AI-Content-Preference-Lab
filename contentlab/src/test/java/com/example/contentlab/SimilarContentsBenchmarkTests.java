package com.example.contentlab;

import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.entity.Content;
import com.example.contentlab.entity.ContentId;
import com.example.contentlab.repository.ContentRepository;
import com.example.contentlab.repository.RecommendationHistoryRepository;
import com.example.contentlab.service.AiRecommendationClient;
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
import tools.jackson.databind.json.JsonMapper;

import java.time.Duration;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Base64;
import java.util.Comparator;
import java.util.HashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.concurrent.Callable;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.function.Supplier;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

@EnabledIfEnvironmentVariable(named = "CONTENTLAB_SIMILAR_BENCHMARK", matches = "true")
@SpringBootTest(properties = {
        "spring.datasource.hikari.read-only=true",
        "spring.jpa.hibernate.ddl-auto=none",
        "spring.sql.init.mode=never",
        "spring.jpa.show-sql=false",
        "spring.data.redis.host=127.0.0.1",
        "spring.data.redis.port=16379",
        "spring.data.redis.database=4",
        "contentlab.cache.enabled=false"
})
class SimilarContentsBenchmarkTests {
    private static final JsonMapper JSON = JsonMapper.builder().build();
    private static final int REQUESTS = 24;
    private final ThreadLocal<RequestTiming> active = new ThreadLocal<>();

    @Autowired
    private ContentRepository repository;

    @Autowired
    private StringRedisTemplate redis;

    @MockitoBean
    private JdbcTemplate jdbc;

    @DynamicPropertySource
    static void testJwtKey(DynamicPropertyRegistry registry) {
        registry.add("JWT_SECRET", () -> Base64.getEncoder().encodeToString(new byte[32]));
    }

    @Test
    void comparesOriginalWithProductionServiceOnTheSameReadOnlyCatalog() throws Exception {
        List<Content> catalog = repository.findByExcludedFalse();
        List<Content> queries = catalog.stream().limit(8).toList();
        assertFalse(queries.isEmpty());
        System.out.printf("Catalog size=%d SQL requests use live read-only MySQL and bypass Redis%n", catalog.size());

        ContentRepository timed = mock(ContentRepository.class);
        when(timed.findById(any(ContentId.class))).thenAnswer(call ->
                timeQuery(() -> repository.findById(call.getArgument(0))));
        when(timed.findByExcludedFalse()).thenAnswer(call -> timeQuery(repository::findByExcludedFalse));
        var service = new ContentService(timed, mock(RecommendationHistoryRepository.class),
                jdbc, mock(AiRecommendationClient.class));

        measureCache(queries, service);
        for (var id : queries) {
            assertEquals(original(repository, id), service.getSimilarContents(id.getType(), id.getId()));
        }
        for (int concurrency : new int[]{1, 4, 8}) {
            boolean baselineFirst = concurrency != 4;
            measure(queries, timed, service, concurrency, baselineFirst);
            measure(queries, timed, service, concurrency, !baselineFirst);
        }
    }

    private void measureCache(List<Content> queries, ContentService service) {
        var ttl = Duration.ofMinutes(5);
        var cache = new CatalogCache(service, redis, true, ttl, ttl, ttl);
        var hit = new long[queries.size()];
        var miss = new long[queries.size()];
        for (int i = 0; i < queries.size(); i++) {
            var id = queries.get(i);
            String key = "contentlab:catalog:v1:similar:" + id.getType() + ":" + id.getId();
            assertFalse(Boolean.TRUE.equals(redis.hasKey(key)), "use a fresh isolated Redis");
            var sample = new RequestTiming();
            active.set(sample);
            try {
                long started = System.nanoTime();
                var uncached = cache.similar(id.getType(), id.getId());
                miss[i] = System.nanoTime() - started;
                assertTrue(sample.queryNanos > 0);
                assertTrue(Boolean.TRUE.equals(redis.hasKey(key)));

                sample.queryNanos = 0;
                started = System.nanoTime();
                var cached = cache.similar(id.getType(), id.getId());
                hit[i] = System.nanoTime() - started;
                assertEquals(0, sample.queryNanos);
                assertEquals(uncached, cached);
            } finally {
                active.remove();
            }
        }
        System.out.printf(Locale.ROOT, "SIMILAR real Redis n=%d miss-p50=%.3fms hit-p50=%.3fms%n",
                queries.size(), percentile(miss, 0.5), percentile(hit, 0.5));
    }

    private void measure(List<Content> queries, ContentRepository timed, ContentService service,
                         int concurrency, boolean baseline) throws Exception {
        List<Callable<RequestTiming>> jobs = new ArrayList<>();
        for (int i = 0; i < REQUESTS; i++) {
            Content id = queries.get(i % queries.size());
            jobs.add(() -> {
                var sample = new RequestTiming();
                active.set(sample);
                long start = System.nanoTime();
                try {
                    if (baseline) {
                        original(timed, id);
                    } else {
                        service.getSimilarContents(id.getType(), id.getId());
                    }
                    sample.elapsedNanos = System.nanoTime() - start;
                    return sample;
                } finally {
                    active.remove();
                }
            });
        }
        try (var executor = Executors.newFixedThreadPool(concurrency)) {
            for (int index = 0; index < concurrency; index++) {
                executor.submit(jobs.get(index)).get(15, TimeUnit.SECONDS);
            }
            long start = System.nanoTime();
            var futures = executor.invokeAll(jobs, 90, TimeUnit.SECONDS);
            long elapsed = System.nanoTime() - start;
            var total = new long[REQUESTS];
            var database = new long[REQUESTS];
            var outsideRepository = new long[REQUESTS];
            for (int i = 0; i < REQUESTS; i++) {
                var sample = futures.get(i).get();
                total[i] = sample.elapsedNanos;
                database[i] = sample.queryNanos;
                outsideRepository[i] = sample.elapsedNanos - sample.queryNanos;
            }
            System.out.printf(Locale.ROOT,
                    "SIMILAR %s concurrency=%d n=%d p50=%.3fms p95=%.3fms db-p50=%.3fms "
                    + "outside-repository-p50=%.3fms rate=%.2f/s%n",
                    baseline ? "baseline" : "optimized", concurrency, REQUESTS,
                    percentile(total, 0.5), percentile(total, 0.95), percentile(database, 0.5),
                    percentile(outsideRepository, 0.5), REQUESTS * 1_000_000_000.0 / elapsed);
        }
    }

    private <T> T timeQuery(Supplier<T> query) {
        long start = System.nanoTime();
        try {
            return query.get();
        } finally {
            var sample = active.get();
            if (sample != null) {
                sample.queryNanos += System.nanoTime() - start;
            }
        }
    }

    private static double percentile(long[] values, double fraction) {
        Arrays.sort(values);
        return values[(int) Math.ceil(fraction * values.length) - 1] / 1_000_000.0;
    }

    private static List<ContentResponse> original(ContentRepository repository, Content id) {
        var target = repository.findById(new ContentId(id.getId(), id.getType()))
                .filter(item -> !item.isExcluded()).orElseThrow();
        return repository.findByExcludedFalse().stream()
                .filter(item -> !(item.getId().equals(id.getId()) && item.getType().equals(id.getType())))
                .sorted(Comparator.comparingDouble((Content item) -> originalScore(target, item)).reversed())
                .limit(6).map(ContentResponse::from).toList();
    }

    private static double originalScore(Content target, Content candidate) {
        var targetGenres = genres(target.getGenreIds());
        var candidateGenres = genres(candidate.getGenreIds());
        var intersection = new HashSet<>(targetGenres);
        intersection.retainAll(candidateGenres);
        var union = new HashSet<>(targetGenres);
        union.addAll(candidateGenres);
        double genre = union.isEmpty() ? 0 : (double) intersection.size() / union.size() * 50;
        double type = target.getType().equals(candidate.getType()) ? 20 : 0;
        double rating = candidate.getRating() == null ? 0 : candidate.getRating();
        double popularity = candidate.getPopularity() == null ? 0 : candidate.getPopularity();
        return genre + type + Math.min(10, Math.max(0, rating)) / 10 * 20
                + Math.min(Math.max(0, popularity) / 100, 1.0) * 10;
    }

    private static Set<Integer> genres(String value) {
        var genres = new HashSet<Integer>();
        if (value == null || value.isBlank()) {
            return genres;
        }
        try {
            var nodes = JSON.readTree(value);
            if (nodes.isArray()) {
                for (var node : nodes) {
                    if (node.isIntegralNumber()) {
                        genres.add(node.asInt());
                    }
                }
            }
        } catch (Exception error) {
            return Set.of();
        }
        return genres;
    }

    private static class RequestTiming {
        long queryNanos;
        long elapsedNanos;
    }
}
