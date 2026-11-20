package com.example.contentlab.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.TreeMap;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.NOT_FOUND;

@Service
public class TasteProfileService {
    private static final List<String> DIMENSIONS = List.of("genres", "story", "mood", "pacing");

    private final JdbcTemplate jdbc;
    private final JsonMapper json = JsonMapper.builder().build();

    public TasteProfileService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Map<String, Object> getProfile(long memberId) {
        WebtoonSchemaGuard.requireReady(jdbc);
        String survey = jdbc.query("SELECT survey FROM member_taste_surveys WHERE member_id=?",
                rs -> rs.next() ? rs.getString(1) : "{}", memberId);
        String profile = jdbc.query("SELECT profile FROM member_taste_profiles WHERE member_id=?",
                rs -> rs.next() ? rs.getString(1) : "{}", memberId);
        return Map.of("survey", parseObject(survey), "profile", parseObject(profile));
    }

    @Transactional
    public Map<String, Object> saveSurvey(long memberId, Map<String, Object> request) {
        lockMember(memberId);
        Map<String, Object> survey = normalizeSurvey(request);
        String encoded = writeJson(survey);
        jdbc.update("""
                INSERT INTO member_taste_surveys(member_id, survey) VALUES (?, ?)
                ON DUPLICATE KEY UPDATE survey=VALUES(survey), updated_at=CURRENT_TIMESTAMP
                """, memberId, encoded);
        return rebuild(memberId);
    }

    @Transactional
    public Map<String, Object> saveFeedback(long memberId, String type, long contentId, int rating) {
        if (!"webtoon".equals(type) || rating < -1 || rating > 1) {
            throw new ResponseStatusException(BAD_REQUEST, "웹툰 유형과 -1, 0, 1 평가만 지원합니다.");
        }
        lockMember(memberId);
        Integer exists = jdbc.query("""
                SELECT 1 FROM contents c
                WHERE c.id=? AND c.type=? AND c.is_excluded=FALSE
                AND EXISTS (SELECT 1 FROM webtoon_metadata w
                            WHERE w.content_id=c.id AND w.content_type=c.type)
                """, rs -> rs.next() ? 1 : null, contentId, type);
        if (exists == null) {
            throw new ResponseStatusException(NOT_FOUND, "평가할 웹툰을 찾을 수 없습니다.");
        }
        jdbc.update("""
                INSERT INTO member_content_feedback(member_id, content_id, content_type, rating)
                VALUES (?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE rating=VALUES(rating), updated_at=CURRENT_TIMESTAMP
                """, memberId, contentId, type, rating);
        return rebuild(memberId);
    }

    @Transactional
    public Map<String, Object> deleteFeedback(long memberId, String type, long contentId) {
        if (!"webtoon".equals(type)) {
            throw new ResponseStatusException(BAD_REQUEST, "웹툰 평가만 삭제할 수 있습니다.");
        }
        lockMember(memberId);
        jdbc.update("DELETE FROM member_content_feedback WHERE member_id=? AND content_type=? AND content_id=?",
                memberId, type, contentId);
        return rebuild(memberId);
    }

    private Map<String, Object> rebuild(long memberId) {
        Map<String, Map<String, Double>> totals = new LinkedHashMap<>();
        Map<String, Map<String, Double>> weights = new LinkedHashMap<>();
        for (String dimension : DIMENSIONS) {
            totals.put(dimension, new TreeMap<>());
            weights.put(dimension, new TreeMap<>());
        }

        String surveyJson = jdbc.query("SELECT survey FROM member_taste_surveys WHERE member_id=?",
                rs -> rs.next() ? rs.getString(1) : "{}", memberId);
        JsonNode survey = parseJson(surveyJson);
        for (String dimension : DIMENSIONS) {
            addSignal(totals, weights, dimension, survey.path(dimension), 1.0, 1.0);
        }

        List<Map<String, Object>> feedback = jdbc.query("""
                SELECT f.rating, w.genre_tags, w.story_tags, w.mood_tags, w.pacing
                FROM member_content_feedback f
                JOIN webtoon_metadata w
                  ON w.content_id=f.content_id AND w.content_type=f.content_type
                WHERE f.member_id=? AND f.content_type='webtoon'
                ORDER BY f.content_id
                """, (rs, row) -> Map.of(
                "rating", rs.getInt("rating"),
                "genres", nullable(rs.getString("genre_tags")),
                "story", nullable(rs.getString("story_tags")),
                "mood", nullable(rs.getString("mood_tags")),
                "pacing", nullable(rs.getString("pacing"))), memberId);

        for (Map<String, Object> item : feedback) {
            int rating = (int) item.get("rating");
            if (rating == 0) continue;
            for (String dimension : DIMENSIONS) {
                String raw = (String) item.get(dimension);
                if ("pacing".equals(dimension)) {
                    addValue(totals, weights, dimension, raw, rating * 3.0, 3.0);
                } else {
                    addSignal(totals, weights, dimension, parseJson(raw), rating * 3.0, 3.0);
                }
            }
        }

        Map<String, Object> dimensions = new LinkedHashMap<>();
        for (String dimension : DIMENSIONS) {
            Map<String, Double> scores = new LinkedHashMap<>();
            for (String feature : weights.get(dimension).keySet()) {
                scores.put(feature, Math.round(totals.get(dimension).get(feature)
                        / weights.get(dimension).get(feature) * 10000.0) / 10000.0);
            }
            dimensions.put(dimension, scores);
        }
        Map<String, Object> profile = Map.of("version", 1, "dimensions", dimensions);
        jdbc.update("""
                INSERT INTO member_taste_profiles(member_id, profile, revision)
                VALUES (?, ?, 1)
                ON DUPLICATE KEY UPDATE profile=VALUES(profile),
                    revision=revision+1, updated_at=CURRENT_TIMESTAMP
                """, memberId, writeJson(profile));
        return getProfile(memberId);
    }

    private void lockMember(long memberId) {
        // Lock before the first snapshot read so rebuild can see the preceding writer's commit.
        Boolean exists = jdbc.query("SELECT id FROM members WHERE id=? FOR UPDATE",
                (ResultSetExtractor<Boolean>) rs -> rs.next(), memberId);
        WebtoonSchemaGuard.requireReady(jdbc);
        if (!Boolean.TRUE.equals(exists)) {
            throw new ResponseStatusException(NOT_FOUND, "회원을 찾을 수 없습니다.");
        }
    }

    private Map<String, Object> normalizeSurvey(Map<String, Object> request) {
        Map<String, Object> survey = new LinkedHashMap<>();
        for (String dimension : DIMENSIONS) {
            Object raw = request.get(dimension);
            List<String> values = new ArrayList<>();
            if (raw instanceof String value) raw = List.of(value);
            if (raw instanceof List<?> items) {
                for (Object item : items) {
                    if (!(item instanceof String value) || value.isBlank() || value.length() > 40) {
                        throw new ResponseStatusException(BAD_REQUEST, "취향 항목은 1~40자 문자열이어야 합니다.");
                    }
                    String normalized = value.trim().toLowerCase(java.util.Locale.ROOT);
                    if (!values.contains(normalized)) values.add(normalized);
                    if (values.size() > 10) {
                        throw new ResponseStatusException(BAD_REQUEST, "항목별 선택은 최대 10개입니다.");
                    }
                }
            } else if (raw != null) {
                throw new ResponseStatusException(BAD_REQUEST, "취향 항목 형식이 올바르지 않습니다.");
            }
            survey.put(dimension, values);
        }
        return survey;
    }

    private void addSignal(Map<String, Map<String, Double>> totals,
            Map<String, Map<String, Double>> weights, String dimension,
            JsonNode values, double signal, double weight) {
        if (values.isTextual()) {
            addValue(totals, weights, dimension, values.asString(), signal, weight);
        } else if (values.isArray()) {
            java.util.Set<String> seen = new java.util.HashSet<>();
            for (JsonNode value : values) {
                if (value.isTextual()) {
                    String normalized = value.asString().trim().toLowerCase(java.util.Locale.ROOT);
                    if (seen.add(normalized)) addValue(totals, weights, dimension, normalized, signal, weight);
                }
            }
        }
    }

    private void addValue(Map<String, Map<String, Double>> totals,
            Map<String, Map<String, Double>> weights, String dimension,
            String raw, double signal, double weight) {
        String value = raw == null ? "" : raw.trim().toLowerCase(java.util.Locale.ROOT);
        if (value.isEmpty() || "null".equals(value) || value.length() > 40) return;
        totals.get(dimension).merge(value, signal, Double::sum);
        weights.get(dimension).merge(value, weight, Double::sum);
    }

    private JsonNode parseJson(String raw) {
        try { return json.readTree(raw == null || raw.isBlank() ? "{}" : raw); }
        catch (Exception ignored) { return json.createObjectNode(); }
    }

    private Map<String, Object> parseObject(String raw) {
        try { return json.readValue(raw == null || raw.isBlank() ? "{}" : raw,
                json.getTypeFactory().constructMapType(Map.class, String.class, Object.class)); }
        catch (Exception ignored) { return Map.of(); }
    }

    private String writeJson(Object value) {
        try { return json.writeValueAsString(value); }
        catch (tools.jackson.core.JacksonException e) { throw new IllegalStateException("JSON 직렬화에 실패했습니다.", e); }
    }

    private static String nullable(String value) { return value == null ? "null" : value; }
}
