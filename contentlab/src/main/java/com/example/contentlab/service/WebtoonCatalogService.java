package com.example.contentlab.service;

import com.example.contentlab.dto.WebtoonResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Locale;

import static org.springframework.http.HttpStatus.BAD_REQUEST;
import static org.springframework.http.HttpStatus.NOT_FOUND;

@Service
public class WebtoonCatalogService {
    private static final int MAX_PAGE = 100;
    private static final int MAX_SIZE = 50;
    private static final String SELECT = """
            SELECT c.id, c.type, c.title, c.overview, c.genre_ids, c.poster_url,
                   w.source_provider, x.external_id, w.service_platform, w.official_url,
                   w.authors, w.genre_tags, w.story_tags, w.mood_tags, w.pacing, w.serial_status
            FROM contents c
            JOIN webtoon_metadata w ON w.content_id=c.id AND w.content_type=c.type
            JOIN content_external_ids x
              ON x.provider_code=w.source_provider AND x.content_id=c.id AND x.content_type=c.type
            WHERE c.type='webtoon' AND c.is_excluded=FALSE
            """;

    private final JdbcTemplate jdbc;
    private final CatalogCache cache;
    private final Duration listTtl;

    public WebtoonCatalogService(JdbcTemplate jdbc, CatalogCache cache,
            @Value("${contentlab.cache.webtoon-list-ttl:60s}") Duration listTtl) {
        this.jdbc = jdbc;
        this.cache = cache;
        this.listTtl = listTtl;
    }

    public List<WebtoonResponse> search(String keyword, String genre, String status, int page, int size) {
        if (page < 1 || page > MAX_PAGE || size < 1 || size > MAX_SIZE) {
            throw new ResponseStatusException(BAD_REQUEST, "page는 1~100, size는 1~50이어야 합니다.");
        }
        String titleOrAuthor = normalize(keyword, 100);
        String genreTag = normalize(genre, 40);
        String serialStatus = normalize(status, 40);
        String key = page + ":" + size + ":" + encode(titleOrAuthor) + ":" + encode(genreTag) + ":" + encode(serialStatus);
        return cache.webtoonList(key, listTtl,
                () -> queryList(titleOrAuthor, genreTag, serialStatus, size, (page - 1) * size));
    }

    private List<WebtoonResponse> queryList(String keyword, String genre, String status, int size, int offset) {
        WebtoonSchemaGuard.requireReady(jdbc);
        var sql = new StringBuilder(SELECT);
        var parameters = new ArrayList<>();
        if (!keyword.isEmpty()) {
            sql.append("""
                     AND (LOWER(c.title) LIKE ? ESCAPE '!' OR EXISTS (
                         SELECT 1 FROM JSON_TABLE(w.authors, '$[*]'
                             COLUMNS (tag VARCHAR(255) PATH '$' NULL ON ERROR)) AS author_tags
                         WHERE LOWER(author_tags.tag) LIKE ? ESCAPE '!'
                     ))
                    """);
            String pattern = "%" + keyword.replace("!", "!!").replace("%", "!%").replace("_", "!_") + "%";
            parameters.add(pattern);
            parameters.add(pattern);
        }
        if (!genre.isEmpty()) {
            // In the full catalog join, MySQL 8.4 can lose matching tags with correlated EXISTS.
            sql.append("""
                     AND (
                         SELECT COUNT(*) FROM JSON_TABLE(w.genre_tags, '$[*]'
                             COLUMNS (tag VARCHAR(255) PATH '$' NULL ON ERROR)) AS parsed_genres
                         WHERE LOWER(TRIM(parsed_genres.tag)) = ?
                     ) > 0
                    """);
            parameters.add(genre);
        }
        if (!status.isEmpty()) {
            sql.append(" AND LOWER(TRIM(w.serial_status)) = ?");
            parameters.add(status);
        }
        sql.append(" ORDER BY c.id LIMIT ? OFFSET ?");
        parameters.add(size);
        parameters.add(offset);
        return jdbc.query(sql.toString(), this::map, parameters.toArray());
    }

    private static String normalize(String value, int maxLength) {
        String normalized = value == null ? "" : value.strip().toLowerCase(Locale.ROOT);
        if (normalized.length() > maxLength) {
            throw new ResponseStatusException(BAD_REQUEST, "검색 또는 필터 값이 너무 깁니다.");
        }
        return normalized;
    }

    private static String encode(String value) {
        return Base64.getUrlEncoder().withoutPadding().encodeToString(value.getBytes(StandardCharsets.UTF_8));
    }

    public WebtoonResponse get(long id) {
        WebtoonSchemaGuard.requireReady(jdbc);
        return jdbc.query(SELECT + " AND c.id=?", this::map, id).stream().findFirst()
                .orElseThrow(() -> new ResponseStatusException(NOT_FOUND, "웹툰을 찾을 수 없습니다."));
    }

    private WebtoonResponse map(java.sql.ResultSet rs, int row) throws java.sql.SQLException {
        return new WebtoonResponse(
                rs.getLong("id"), rs.getString("type"), rs.getString("title"), rs.getString("overview"),
                rs.getString("genre_ids"), rs.getString("poster_url"), rs.getString("source_provider"),
                rs.getString("external_id"), rs.getString("service_platform"), rs.getString("official_url"),
                rs.getString("authors"), rs.getString("genre_tags"), rs.getString("story_tags"),
                rs.getString("mood_tags"), rs.getString("pacing"), rs.getString("serial_status"));
    }
}
