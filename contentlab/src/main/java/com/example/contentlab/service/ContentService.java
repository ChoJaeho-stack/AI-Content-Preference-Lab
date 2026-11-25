package com.example.contentlab.service;
import com.example.contentlab.entity.ContentId;

import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.entity.Content;
import com.example.contentlab.entity.RecommendationHistory;
import com.example.contentlab.repository.ContentRepository;
import com.example.contentlab.repository.RecommendationHistoryRepository;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Sort;
import org.springframework.data.jpa.domain.Specification;
import org.springframework.jdbc.core.JdbcTemplate;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.util.HashMap;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Locale;
import java.util.Objects;
import java.util.PriorityQueue;
import java.util.Set;

@Service
public class ContentService {
    private static final Logger LOGGER = LoggerFactory.getLogger(ContentService.class);
    private static final int SIMILAR_LIMIT = 6;
    private static final Comparator<SimilarCandidate> SIMILAR_ORDER =
            Comparator.comparingDouble(SimilarCandidate::score).reversed()
                    .thenComparingInt(SimilarCandidate::position);

    private record SimilarCandidate(Content content, double score, int position) {}

    private final JdbcTemplate personalizationJdbc;
    private final ContentRepository contentRepository;
    private final RecommendationHistoryRepository historyRepository;
    private final AiRecommendationClient recommendationClient;
    private final JsonMapper jsonMapper = JsonMapper.builder().build();

    public ContentService(
            ContentRepository contentRepository,
            RecommendationHistoryRepository historyRepository,
            JdbcTemplate personalizationJdbc,
            AiRecommendationClient recommendationClient) {

        this.contentRepository = contentRepository;
        this.historyRepository = historyRepository;
        this.personalizationJdbc = personalizationJdbc;
        this.recommendationClient = recommendationClient;
    }

    public List<ContentResponse> getContents() {
        return contentRepository.findByExcludedFalse()
                .stream()
                .map(ContentResponse::from)
                .toList();
    }

    public List<ContentResponse> getContentsByType(String type) {
        return contentRepository.findByTypeAndExcludedFalse(type)
                .stream()
                .map(ContentResponse::from)
                .toList();
    }

    public long getCount() {
        return contentRepository.countByExcludedFalse();
    }

    // 콘텐츠 검색 및 필터링

public ContentResponse getContentDetail(String type, Long id) {
    return contentRepository.findById(new ContentId(id, type))
            .filter(content -> !content.isExcluded())
            .map(ContentResponse::from)
            .orElseThrow(() -> new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.NOT_FOUND,
                    "콘텐츠를 찾을 수 없습니다."
            ));
}

// 유사 콘텐츠 추천
public List<ContentResponse> getSimilarContents(String type, Long id) {
    long started = System.nanoTime();
    Content target = contentRepository.findById(new ContentId(id, type))
            .filter(content -> !content.isExcluded())
            .orElseThrow(() -> new org.springframework.web.server.ResponseStatusException(
                    org.springframework.http.HttpStatus.NOT_FOUND,
                    "콘텐츠를 찾을 수 없습니다."
            ));

    List<Content> catalog = contentRepository.findByExcludedFalse();
    long loaded = System.nanoTime();
    Map<String, Set<Integer>> genreSets = new HashMap<>();
    Set<Integer> targetGenres = genreSets.computeIfAbsent(target.getGenreIds(), this::parseGenres);
    var best = new PriorityQueue<>(SIMILAR_LIMIT, SIMILAR_ORDER.reversed());
    for (int i = 0; i < catalog.size(); i++) {
        Content candidate = catalog.get(i);
        if ("webtoon".equals(type) && !type.equals(candidate.getType())) {
            continue;
        }
        if (Objects.equals(candidate.getId(), id) && type.equals(candidate.getType())) {
            continue;
        }
        Set<Integer> candidateGenres = genreSets.computeIfAbsent(candidate.getGenreIds(), this::parseGenres);
        var ranked = new SimilarCandidate(candidate,
                calculateSimilarity(target, candidate, targetGenres, candidateGenres), i);
        if (best.size() < SIMILAR_LIMIT) {
            best.add(ranked);
        } else if (SIMILAR_ORDER.compare(ranked, best.element()) < 0) {
            best.remove();
            best.add(ranked);
        }
    }
    var result = best.stream()
            .sorted(SIMILAR_ORDER)
            .map(entry -> ContentResponse.from(entry.content()))
            .toList();
    LOGGER.debug("Similar catalog query_ms={} ranking_ms={} candidates={}",
            (loaded - started) / 1_000_000.0, (System.nanoTime() - loaded) / 1_000_000.0, catalog.size());
    return result;
}

// 콘텐츠 유사도 계산
private double calculateSimilarity(Content target, Content candidate,
        Set<Integer> targetGenres, Set<Integer> candidateGenres) {
    int intersection = 0;
    for (Integer genre : candidateGenres) {
        if (targetGenres.contains(genre)) {
            intersection++;
        }
    }
    int union = targetGenres.size() + candidateGenres.size() - intersection;
    double genreScore = union == 0 ? 0 : (double) intersection / union * 50;

    double typeScore = target.getType().equals(candidate.getType()) ? 20 : 0;

    double rating = candidate.getRating() == null ? 0 : candidate.getRating();
    double ratingScore = Math.min(10, Math.max(0, rating)) / 10 * 20;

    double popularity = candidate.getPopularity() == null ? 0 : candidate.getPopularity();
    double popularityScore = Math.min(Math.max(0, popularity) / 100, 1.0) * 10;

    return genreScore + typeScore + ratingScore + popularityScore;
}

// JSON 장르 데이터 변환
private java.util.Set<Integer> parseGenres(String genres) {

    java.util.Set<Integer> result = new java.util.HashSet<>();

    if (genres == null || genres.isBlank()) {
        return result;
    }

    try {
        var nodes = jsonMapper.readTree(genres);

        if (nodes.isArray()) {
            for (var node : nodes) {
                if (node.isIntegralNumber()) {
                    result.add(node.asInt());
                }
            }
        }
    } catch (Exception e) {
        return java.util.Set.of();
    }

    return result;
}

    public Page<ContentResponse> searchContents(
            String keyword,
            String type,
            String ott,
            String sort,
            int page,
            int size) {

        Specification<Content> spec =
                (root, query, cb) ->
                        cb.isFalse(root.get("excluded"));

        // 작품명 검색
        if (keyword != null && !keyword.isBlank()) {
            spec = spec.and((root, query, cb) ->
                    cb.like(
                            cb.lower(root.get("title")),
                            "%" + keyword.trim().toLowerCase(Locale.ROOT) + "%"
                    ));
        }

        // 콘텐츠 유형 필터
        if (type != null && !type.isBlank()) {
            spec = spec.and((root, query, cb) ->
                    cb.equal(root.get("type"), type));
        }

        // OTT 플랫폼 필터
        if (ott != null && !ott.isBlank()) {
            spec = spec.and((root, query, cb) ->
                    cb.like(
                            cb.lower(root.get("ott")),
                            "%" + ott.trim().toLowerCase(Locale.ROOT) + "%"
                    ));
        }

        // 정렬 방식
        Sort sorting = switch (sort == null ? "" : sort) {
            case "rating" -> Sort.by("rating").descending();
            case "title" -> Sort.by("title").ascending();
            default -> Sort.by("popularity").descending();
        };

        sorting = sorting.and(Sort.by("id", "type"));

        // 페이지네이션
        PageRequest pageable = PageRequest.of(
                Math.max(page, 0),
                Math.max(1, Math.min(size, 100)),
                sorting
        );

        return contentRepository
                .findAll(spec, pageable)
                .map(ContentResponse::from);
    }

  
        
    public Map<String, Object> recommendWebtoonGuest(Map<String, Object> request) {
        Map<String, Object> payload = new HashMap<>();
        for (String field : List.of("taste", "liked", "disliked", "preference")) {
            Object raw = request.get(field);
            if (raw == null) continue;
            if (!(raw instanceof String value) || value.length() > 1000) {
                throw new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.BAD_REQUEST, "취향 입력 형식을 확인해주세요.");
            }
            payload.put(field, value);
        }
        payload.putIfAbsent("taste", "웹툰 추천");
        Object survey = request.get("survey");
        if (survey != null) {
            if (!(survey instanceof Map<?, ?> values)) {
                throw new org.springframework.web.server.ResponseStatusException(
                        org.springframework.http.HttpStatus.BAD_REQUEST, "취향 설문 형식을 확인해주세요.");
            }
            Map<String, Object> dimensions = new HashMap<>();
            for (String dimension : List.of("genres", "story", "mood", "pacing")) {
                dimensions.put(dimension, values.get(dimension));
            }
            payload.put("tasteProfile", TasteProfileService.previewProfile(dimensions));
        }
        WebtoonSchemaGuard.requireReady(personalizationJdbc);
        payload.put("contentType", "webtoon");
        payload.put("publicPreview", true);
        return recommendationClient.recommend(payload);
    }

public Map<String, Object> recommend(Map<String, String> request, Long memberId) {
    String taste = request.get("taste");
    if (taste == null || taste.isBlank()) {
        throw new org.springframework.web.server.ResponseStatusException(
                org.springframework.http.HttpStatus.BAD_REQUEST, "취향을 입력하세요.");
    }
    if ("webtoon".equals(request.get("contentType"))) {
        WebtoonSchemaGuard.requireReady(personalizationJdbc);
    }
    List<Map<String, Object>> favorites = personalizationJdbc.query("""
            SELECT c.id, c.type, c.title
            FROM favorites f
            JOIN contents c ON f.content_id = c.id AND f.content_type = c.type
            WHERE f.member_id = ?
            ORDER BY f.created_at DESC, c.type, c.id
            LIMIT 30
            """, (row, index) -> Map.of(
            "id", row.getLong("id"), "type", row.getString("type"),
            "title", row.getString("title")), memberId);

    List<Integer> preferredGenres = personalizationJdbc.queryForList("""
            SELECT g.genre_id
            FROM favorites f
            JOIN contents c ON f.content_id = c.id AND f.content_type = c.type
            JOIN JSON_TABLE(c.genre_ids, '$[*]' COLUMNS (genre_id INT PATH '$')) g
            WHERE f.member_id = ? AND g.genre_id IS NOT NULL
            GROUP BY g.genre_id
            ORDER BY COUNT(DISTINCT c.id, c.type) DESC, g.genre_id
            LIMIT 5
            """, Integer.class, memberId);

    Map<String, Object> payload = new HashMap<>();
    for (String field : List.of("taste", "liked", "disliked", "preference")) {
        if (request.get(field) != null) {
            payload.put(field, request.get(field));
        }
    }
    if (request.get("contentType") != null) {
        payload.put("contentType", request.get("contentType"));
    }
    payload.put("favorites", favorites);
    payload.put("preferredGenres", preferredGenres);
    payload.put("recentHistory", recentRecommendations(memberId));
    if ("webtoon".equals(request.get("contentType"))) {
        payload.put("tasteProfile", storedTasteProfile(memberId));
    }

    Map<String, Object> result = recommendationClient.recommend(payload);

    RecommendationHistory history = new RecommendationHistory(
            memberId,
            request.get("liked"),
            request.get("disliked"),
            request.get("preference"),
            jsonMapper.writeValueAsString(result)
    );

        historyRepository.save(history);

    return result;
}

private Map<String, Object> storedTasteProfile(Long memberId) {
    String stored = personalizationJdbc.query("""
            SELECT profile FROM member_taste_profiles WHERE member_id=?
            """, rs -> rs.next() ? rs.getString(1) : "{}", memberId);
    try {
        return jsonMapper.readValue(stored,
                jsonMapper.getTypeFactory().constructMapType(Map.class, String.class, Object.class));
    } catch (tools.jackson.core.JacksonException | IllegalArgumentException ignored) {
        return Map.of();
    }
}

private List<String> recentRecommendations(Long memberId) {
    var recent = new LinkedHashSet<String>();
    for (RecommendationHistory history : getHistory(memberId)) {
        if (history.getResult() == null || history.getResult().isBlank()) {
            continue;
        }
        JsonNode result;
        try {
            result = jsonMapper.readTree(history.getResult());
            if (result.isString()) {
                result = jsonMapper.readTree(result.asString());
            }
        } catch (tools.jackson.core.JacksonException | IllegalArgumentException ignored) {
            continue;
        }
        JsonNode recommendations = result.path("recommendations");
        if (!recommendations.isArray()) {
            continue;
        }
        for (JsonNode item : recommendations) {
            String type = item.path("type").asString("");
            JsonNode idNode = item.path("id");
            String id = idNode.isIntegralNumber() ? idNode.toString() : idNode.asString("");
            if (!type.isBlank() && id.matches("[0-9]+")) {
                recent.add(type + ":" + id);
            }
        }
    }
    return List.copyOf(recent);
}

public List<RecommendationHistory> getHistory(Long memberId) {
    return historyRepository
            .findTop20ByMemberIdOrderByCreatedAtDesc(memberId);
}

}
