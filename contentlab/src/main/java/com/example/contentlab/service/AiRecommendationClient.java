package com.example.contentlab.service;

import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.core.JacksonException;
import tools.jackson.core.type.TypeReference;
import tools.jackson.databind.DeserializationFeature;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.net.SocketTimeoutException;
import java.net.URI;
import java.time.Duration;
import java.util.HashSet;
import java.util.Map;

@Component
public class AiRecommendationClient {
    private static final MediaType JSON_SUFFIX = MediaType.parseMediaType("application/*+json");
    private final JsonMapper json = JsonMapper.builder()
            .enable(DeserializationFeature.FAIL_ON_TRAILING_TOKENS)
            .build();
    private final RestClient client;
    private final URI endpoint;

    @Autowired
    public AiRecommendationClient(
            @Value("${contentlab.ai.recommend-url:http://127.0.0.1:8000/recommend}") URI endpoint,
            @Value("${contentlab.ai.connect-timeout:2s}") Duration connectTimeout,
            @Value("${contentlab.ai.read-timeout:60s}") Duration readTimeout) {
        this(endpoint, createClient(connectTimeout, readTimeout));
    }

    public AiRecommendationClient(URI endpoint, RestClient client) {
        this.endpoint = endpoint;
        this.client = client;
    }

    public Map<String, Object> recommend(Map<String, Object> payload) {
        ResponseEntity<String> response;
        try {
            response = client.post().uri(endpoint)
                    .contentType(MediaType.APPLICATION_JSON)
                    .accept(MediaType.APPLICATION_JSON)
                    .body(payload)
                    .retrieve().toEntity(String.class);
        } catch (RestClientResponseException error) {
            int status = error.getStatusCode().value();
            if (status == 429 || status == 503) {
                throw new ResponseStatusException(HttpStatus.SERVICE_UNAVAILABLE, "AI 추천 서비스가 일시적으로 혼잡합니다.");
            }
            if (status == 504) {
                throw timeout();
            }
            throw gatewayError();
        } catch (RestClientException error) {
            for (Throwable cause = error; cause != null; cause = cause.getCause()) {
                if (cause instanceof SocketTimeoutException) {
                    throw timeout();
                }
            }
            throw gatewayError();
        }

        MediaType contentType = response.getHeaders().getContentType();
        String body = response.getBody();
        if (!response.getStatusCode().is2xxSuccessful() || body == null || contentType == null
                || !(MediaType.APPLICATION_JSON.isCompatibleWith(contentType)
                || JSON_SUFFIX.isCompatibleWith(contentType))) {
            throw gatewayError();
        }
        try {
            JsonNode root = json.readTree(body);
            if (root == null || !root.isObject()) {
                throw gatewayError();
            }
            JsonNode recommendations = root.path("recommendations");
            if (!root.path("taste_analysis").isString()
                    || !recommendations.isArray() || recommendations.size() > 5) {
                throw gatewayError();
            }
            boolean webtoon = "webtoon".equals(payload.get("contentType"));
            if (webtoon && root.has("profile_summary") && !validProfileSummary(root.path("profile_summary"))) {
                throw gatewayError();
            }
            var webtoonIds = new HashSet<Long>();
            for (JsonNode item : recommendations) {
                JsonNode id = item.path("id");
                JsonNode score = item.path("match_score");
                if (!item.isObject() || !id.isIntegralNumber() || !id.canConvertToLong()
                        || id.asLong() <= 0 || !item.path("type").isString()
                        || item.path("type").asString().isBlank() || !item.path("title").isString()
                        || !score.isIntegralNumber() || !score.canConvertToInt()
                        || score.asInt() < 0 || score.asInt() > 100) {
                    throw gatewayError();
                }
                JsonNode personalFit = item.path("personal_fit_score");
                if (webtoon && (!"webtoon".equals(item.path("type").asString())
                        || !webtoonIds.add(id.asLong()) || item.path("title").asString().isBlank()
                        || !item.path("reason").isString() || item.path("reason").asString().isBlank()
                        || (item.has("personal_fit_score") && (!personalFit.isIntegralNumber()
                            || !personalFit.canConvertToInt() || personalFit.asInt() != score.asInt())))) {
                    throw gatewayError();
                }
            }
            return json.convertValue(root, new TypeReference<>() {});
        } catch (JacksonException | IllegalArgumentException error) {
            throw gatewayError();
        }
    }

    private static boolean validProfileSummary(JsonNode summary) {
        if (!summary.isObject()) {
            return false;
        }
        for (JsonNode dimension : summary) {
            if (!dimension.isObject()) {
                return false;
            }
            for (JsonNode weight : dimension) {
                if (!weight.isNumber() || !(weight.asDouble() >= -1 && weight.asDouble() <= 1)) {
                    return false;
                }
            }
        }
        return true;
    }

    private static RestClient createClient(Duration connectTimeout, Duration readTimeout) {
        if (connectTimeout.toMillis() < 1 || readTimeout.toMillis() < 1) {
            throw new IllegalArgumentException("AI timeouts must be at least one millisecond");
        }
        var factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(connectTimeout);
        factory.setReadTimeout(readTimeout);
        return RestClient.builder().requestFactory(factory).build();
    }

    private static ResponseStatusException gatewayError() {
        return new ResponseStatusException(HttpStatus.BAD_GATEWAY, "AI 추천 서비스 응답을 처리할 수 없습니다.");
    }

    private static ResponseStatusException timeout() {
        return new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT, "AI 추천 서비스 응답 시간이 초과되었습니다.");
    }
}
