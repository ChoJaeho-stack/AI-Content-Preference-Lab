package com.example.contentlab;

import com.example.contentlab.repository.ContentRepository;
import com.example.contentlab.repository.RecommendationHistoryRepository;
import com.example.contentlab.service.AiRecommendationClient;
import com.example.contentlab.service.ContentService;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.params.ParameterizedTest;
import org.junit.jupiter.params.provider.ValueSource;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import org.springframework.web.server.ResponseStatusException;

import java.net.InetSocketAddress;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

import static org.junit.jupiter.api.Assertions.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.*;

class AiRecommendationClientTests {
    private static final URI ENDPOINT = URI.create("http://127.0.0.1:8000/recommend");
    private static final Map<String, Object> REQUEST = Map.of("taste", "추천");
    private final RestClient.Builder builder = RestClient.builder();
    private final MockRestServiceServer server = MockRestServiceServer.bindTo(builder).build();
    private final AiRecommendationClient client = new AiRecommendationClient(ENDPOINT, builder.build());

    @Test
    void acceptsEmptyResultsAndKeepsAdditionalResponseFields() {
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess("""
                {"taste_analysis":"추천","recommendations":[],"extra":true}
                """, MediaType.APPLICATION_JSON));
        assertEquals(Map.of("taste_analysis", "추천", "recommendations", List.of(), "extra", true),
                client.recommend(REQUEST));
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            "", "{", "null", "[]",
            "{\"taste_analysis\":[],\"recommendations\":[]}",
            "{\"taste_analysis\":\"ok\",\"recommendations\":{}}",
            "{\"taste_analysis\":\"ok\",\"recommendations\":[]} {}",
            "{\"taste_analysis\":\"ok\",\"recommendations\":[{\"id\":1,\"type\":\"movie\",\"title\":\"Title\",\"match_score\":101}]}"
    })
    void rejectsInvalidResponsesBeforeSavingHistory(String body) {
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess(body, MediaType.APPLICATION_JSON));
        var history = mock(RecommendationHistoryRepository.class);
        var service = new ContentService(mock(ContentRepository.class), history, mock(JdbcTemplate.class), client);
        var error = assertThrows(ResponseStatusException.class,
                () -> service.recommend(Map.of("taste", "추천"), 11L));
        assertEquals(HttpStatus.BAD_GATEWAY, error.getStatusCode());
        verify(history, never()).save(any());
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(ints = {429, 503})
    void mapsUpstreamOverloadWithoutForwardingItsBody(int status) {
        server.expect(requestTo(ENDPOINT)).andRespond(withStatus(HttpStatus.valueOf(status))
                .body("private upstream detail"));
        var error = assertThrows(ResponseStatusException.class, () -> client.recommend(REQUEST));
        assertEquals(HttpStatus.SERVICE_UNAVAILABLE, error.getStatusCode());
        assertFalse(error.getMessage().contains("private upstream detail"));
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {
            """
            {"id":1,"type":"movie","title":"Movie","match_score":80,"reason":"Fantasy"}
            """,
            """
            {"id":1,"type":"webtoon","title":"Duplicate","match_score":80,"reason":"Fantasy"}
            """,
            """
            {"id":2,"type":"webtoon","title":"Missing reason","match_score":80}
            """,
            """
            {"id":2,"type":"webtoon","title":"Fixture","match_score":80,"personal_fit_score":"80","reason":"Fantasy"}
            """,
            """
            {"id":2,"type":"webtoon","title":"Fixture","match_score":80,"personal_fit_score":81,"reason":"Fantasy"}
            """,
            """
            {"id":2,"type":"webtoon","title":"Fixture","match_score":80,"personal_fit_score":101,"reason":"Fantasy"}
            """
    })
    void rejectsInvalidWebtoonCardsBeforeSavingHistory(String invalidCard) {
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess("""
                {"taste_analysis":"ok","recommendations":[
                  {"id":1,"type":"webtoon","title":"Fixture","match_score":80,"personal_fit_score":80,"reason":"Fantasy"},
                  %s
                ]}
                """.formatted(invalidCard), MediaType.APPLICATION_JSON));
        var history = mock(RecommendationHistoryRepository.class);
        var jdbc = mock(JdbcTemplate.class);
        when(jdbc.queryForObject(contains("information_schema.tables"), eq(Integer.class))).thenReturn(5);
        var service = new ContentService(mock(ContentRepository.class), history, jdbc, client);
        var error = assertThrows(ResponseStatusException.class, () -> service.recommend(
                Map.of("taste", "fantasy", "contentType", "webtoon"), 11L));
        assertEquals(HttpStatus.BAD_GATEWAY, error.getStatusCode());
        verify(history, never()).save(any());
        server.verify();
    }

    @ParameterizedTest
    @ValueSource(strings = {"[]", "{\"genres\":[]}", "{\"genres\":{\"fantasy\":\"1\"}}",
            "{\"genres\":{\"fantasy\":1.1}}"})
    void rejectsInvalidWebtoonProfileSummary(String summary) {
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess("""
                {"taste_analysis":"ok","recommendations":[],"profile_summary":%s}
                """.formatted(summary), MediaType.APPLICATION_JSON));
        var error = assertThrows(ResponseStatusException.class,
                () -> client.recommend(Map.of("contentType", "webtoon")));
        assertEquals(HttpStatus.BAD_GATEWAY, error.getStatusCode());
        server.verify();
    }

    @Test
    void acceptsValidOptionalWebtoonFields() {
        server.expect(requestTo(ENDPOINT)).andRespond(withSuccess("""
                {"taste_analysis":"ok","profile_summary":{"genres":{"fantasy":0.5}},"recommendations":[
                  {"id":1,"type":"webtoon","title":"Fixture","match_score":80,"personal_fit_score":80,"reason":"Fantasy"},
                  {"id":2,"type":"webtoon","title":"Fixture 2","match_score":70,"reason":"Fantasy"}
                ]}
                """, MediaType.APPLICATION_JSON));
        var response = client.recommend(Map.of("contentType", "webtoon"));
        assertEquals(Map.of("genres", Map.of("fantasy", 0.5)), response.get("profile_summary"));
        var recommendations = (List<?>) response.get("recommendations");
        assertEquals(80, ((Map<?, ?>) recommendations.getFirst()).get("personal_fit_score"));
        assertFalse(((Map<?, ?>) recommendations.getLast()).containsKey("personal_fit_score"));
        server.verify();
    }

    @Test
    void appliesReadTimeoutEvenAfterReceivingSuccessfulResponseHeaders() throws Exception {
        var http = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        var release = new CountDownLatch(1);
        http.createContext("/recommend", exchange -> {
            try (exchange) {
                exchange.getRequestBody().readAllBytes();
                var body = "{\"taste_analysis\":\"ok\",\"recommendations\":[]}".getBytes(StandardCharsets.UTF_8);
                exchange.getResponseHeaders().set("Content-Type", "application/json");
                exchange.sendResponseHeaders(200, body.length);
                exchange.getResponseBody().write(body, 0, 1);
                exchange.getResponseBody().flush();
                if (release.await(5, TimeUnit.SECONDS)) {
                    exchange.getResponseBody().write(body, 1, body.length - 1);
                }
            } catch (InterruptedException error) {
                Thread.currentThread().interrupt();
            }
        });
        http.start();
        try {
            var endpoint = URI.create("http://127.0.0.1:" + http.getAddress().getPort() + "/recommend");
            var timed = new AiRecommendationClient(endpoint, Duration.ofSeconds(1), Duration.ofMillis(300));
            var error = assertThrows(ResponseStatusException.class, () -> timed.recommend(REQUEST));
            assertEquals(HttpStatus.GATEWAY_TIMEOUT, error.getStatusCode());
        } finally {
            release.countDown();
            http.stop(0);
        }
    }
}
