package com.example.contentlab.service;

import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.dto.WebtoonResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.json.JsonMapper;

import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.function.Supplier;

@Service
public class CatalogCache {
    private static final Logger LOGGER = LoggerFactory.getLogger(CatalogCache.class);
    private static final String PREFIX = "contentlab:catalog:v1:";
    private static final String WEBTOON_GENERATION_KEY = PREFIX + "webtoon:generation";
    private static final TypeReference<List<ContentResponse>> LIST_TYPE = new TypeReference<>() {};
    private static final TypeReference<ContentResponse> DETAIL_TYPE = new TypeReference<>() {};
    private static final TypeReference<List<WebtoonResponse>> WEBTOON_LIST_TYPE = new TypeReference<>() {};

    private final ContentService catalog;
    private final StringRedisTemplate redis;
    private final JsonMapper json = JsonMapper.builder().build();
    private final boolean enabled;
    private final Duration listTtl;
    private final Duration detailTtl;
    private final Duration similarTtl;

    public CatalogCache(ContentService catalog, StringRedisTemplate redis,
            @Value("${contentlab.cache.enabled:false}") boolean enabled,
            @Value("${contentlab.cache.list-ttl:60s}") Duration listTtl,
            @Value("${contentlab.cache.detail-ttl:300s}") Duration detailTtl,
            @Value("${contentlab.cache.similar-ttl:120s}") Duration similarTtl) {
        this.catalog = catalog;
        this.redis = redis;
        this.enabled = enabled;
        this.listTtl = listTtl;
        this.detailTtl = detailTtl;
        this.similarTtl = similarTtl;
    }

    public List<ContentResponse> list(String type) {
        if (type == null || type.isBlank()) {
            return load("list:all", listTtl, LIST_TYPE, catalog::getContents);
        }
        return load("list:type:" + type, listTtl, LIST_TYPE, () -> catalog.getContentsByType(type));
    }

    public ContentResponse detail(String type, Long id) {
        return load("detail:" + type + ":" + id, detailTtl, DETAIL_TYPE,
                () -> catalog.getContentDetail(type, id));
    }

    public List<ContentResponse> similar(String type, Long id) {
        return load("similar:" + type + ":" + id, similarTtl, LIST_TYPE,
                () -> catalog.getSimilarContents(type, id));
    }

    List<WebtoonResponse> webtoonList(String filters, Duration ttl, Supplier<List<WebtoonResponse>> fetch) {
        if (!isEnabled(ttl)) {
            return fetch.get();
        }
        String generation;
        try {
            var values = redis.opsForValue();
            generation = values.get(WEBTOON_GENERATION_KEY);
            if (generation == null) {
                String candidate = UUID.randomUUID().toString();
                generation = Boolean.TRUE.equals(values.setIfAbsent(WEBTOON_GENERATION_KEY, candidate))
                        ? candidate : values.get(WEBTOON_GENERATION_KEY);
            }
        } catch (DataAccessException ignored) {
            logOutcome("webtoon:", "unavailable");
            return fetch.get();
        }
        if (generation == null) {
            return fetch.get();
        }
        return load("webtoon:list:" + generation + ":" + filters, ttl, WEBTOON_LIST_TYPE, fetch);
    }

    private boolean isEnabled(Duration ttl) {
        return enabled && !ttl.isZero() && !ttl.isNegative();
    }

    private <T> T load(String key, Duration ttl, TypeReference<T> valueType, Supplier<T> fetch) {
        if (!isEnabled(ttl)) {
            logOutcome(key, "disabled");
            return fetch.get();
        }
        String redisKey = PREFIX + key;
        try {
            String stored = redis.opsForValue().get(redisKey);
            if (stored != null) {
                try {
                    T value = json.readValue(stored, valueType);
                    if (value != null) {
                        logOutcome(key, "hit");
                        return value;
                    }
                } catch (JacksonException ignored) {
                    // Replace invalid JSON with a fresh value from the catalog.
                }
            }
        } catch (DataAccessException ignored) {
            logOutcome(key, "unavailable");
            return fetch.get();
        }

        logOutcome(key, "miss");
        T value = fetch.get();
        if (value != null) {
            try {
                redis.opsForValue().set(redisKey, json.writeValueAsString(value), ttl);
            } catch (DataAccessException | JacksonException ignored) {
                // Keep serving the catalog when the cache write fails.
                logOutcome(key, "write-failed");
            }
        }
        return value;
    }

    private static void logOutcome(String key, String outcome) {
        if (LOGGER.isDebugEnabled()) {
            LOGGER.debug("Catalog cache operation={} outcome={}", key.substring(0, key.indexOf(':')), outcome);
        }
    }
}
