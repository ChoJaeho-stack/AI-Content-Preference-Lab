package com.example.contentlab;

import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.dto.WebtoonResponse;
import com.example.contentlab.service.CatalogCache;
import com.example.contentlab.service.ContentService;
import com.example.contentlab.service.WebtoonCatalogService;
import io.lettuce.core.ClientOptions;
import io.lettuce.core.SocketOptions;
import org.junit.jupiter.api.Test;
import org.springframework.dao.DataAccessException;
import org.springframework.data.redis.connection.RedisStandaloneConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceClientConfiguration;
import org.springframework.data.redis.connection.lettuce.LettuceConnectionFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;

import java.io.IOException;
import java.net.InetAddress;
import java.net.ServerSocket;
import java.time.Duration;
import java.util.List;

import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.mockito.ArgumentMatchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

class CatalogRedisOutageTests {
    @Test
    void catalogRoutesStillRespondWhenRealRedisClientLosesItsConnection() throws Exception {
        // Own an ephemeral loopback port and reset Redis connections during the handshake.
        try (var endpoint = new ServerSocket(0, 16, InetAddress.getByName("127.0.0.1"))) {
            Thread listener = Thread.startVirtualThread(() -> resetConnections(endpoint));
            try {
                assertCatalogFallback(endpoint.getLocalPort());
            } finally {
                endpoint.close();
                listener.join();
            }
        }
    }

    private static void assertCatalogFallback(int port) throws Exception {
        var timeout = Duration.ofMillis(300);
        var client = LettuceClientConfiguration.builder()
                .commandTimeout(timeout)
                .clientOptions(ClientOptions.builder()
                        .socketOptions(SocketOptions.builder().connectTimeout(timeout).build())
                        .build())
                .build();
        var connectionFactory = new LettuceConnectionFactory(
                new RedisStandaloneConfiguration("127.0.0.1", port), client);
        connectionFactory.afterPropertiesSet();
        try {
            var redis = new StringRedisTemplate(connectionFactory);
            assertThrows(DataAccessException.class, () -> redis.opsForValue().get("outage:probe"));

            var catalog = mock(ContentService.class);
            var film = new ContentResponse(113L, "movie", "Catalog fixture", null, null,
                    null, null, null, null);
            var similar = new ContentResponse(114L, "movie", "Similar fixture", null, null,
                    null, null, null, null);
            when(catalog.getContents()).thenReturn(List.of(film));
            when(catalog.getContentDetail("movie", 113L)).thenReturn(film);
            when(catalog.getSimilarContents("movie", 113L)).thenReturn(List.of(similar));
            var ttl = Duration.ofMinutes(1);
            var cache = new CatalogCache(catalog, redis, true, ttl, ttl, ttl);
            var mvc = MockMvcBuilders.standaloneSetup(new ContentController(catalog, cache)).build();

            mvc.perform(get("/api/contents")).andExpect(status().isOk())
                    .andExpect(jsonPath("$[0].title").value("Catalog fixture"));
            mvc.perform(get("/api/contents/movie/113")).andExpect(status().isOk())
                    .andExpect(jsonPath("$.title").value("Catalog fixture"));
            mvc.perform(get("/api/contents/movie/113/similar")).andExpect(status().isOk())
                    .andExpect(jsonPath("$[0].title").value("Similar fixture"));
            verify(catalog).getContents();
            verify(catalog).getContentDetail("movie", 113L);
            verify(catalog).getSimilarContents("movie", 113L);

            var jdbc = mock(JdbcTemplate.class);
            var webtoon = new WebtoonResponse(115L, "webtoon", "Webtoon fixture", null, null,
                    null, "fixture", "115", "fixture", null, null, null, null, null, null, null);
            when(jdbc.queryForObject(anyString(), eq(Integer.class))).thenReturn(5);
            when(jdbc.query(anyString(), org.mockito.ArgumentMatchers.<RowMapper<WebtoonResponse>>any(),
                    any(Object[].class))).thenReturn(List.of(webtoon));
            var webtoonMvc = MockMvcBuilders.standaloneSetup(
                    new WebtoonController(new WebtoonCatalogService(jdbc, cache, ttl))).build();
            webtoonMvc.perform(get("/api/webtoons")).andExpect(status().isOk())
                    .andExpect(jsonPath("$[0].title").value("Webtoon fixture"));
            verify(jdbc).query(anyString(), org.mockito.ArgumentMatchers.<RowMapper<WebtoonResponse>>any(),
                    eq(20), eq(0));
        } finally {
            connectionFactory.destroy();
        }
    }

    private static void resetConnections(ServerSocket endpoint) {
        while (!endpoint.isClosed()) {
            try (var connection = endpoint.accept()) {
                connection.setSoLinger(true, 0);
            } catch (IOException exception) {
                if (!endpoint.isClosed()) {
                    throw new java.io.UncheckedIOException(exception);
                }
            }
        }
    }
}
