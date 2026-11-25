package com.example.contentlab;

import java.util.List;
import java.util.Map;
import jakarta.annotation.PostConstruct;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;

@RestController
@RequestMapping("/api/favorites")
public class FavoriteController {

    private final JdbcTemplate jdbc;

    @Value("${contentlab.schema.init-enabled:true}")
    private boolean initializeSchema = true;

    public FavoriteController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void init() {
        if (!initializeSchema) {
            return;
        }
        jdbc.execute("""
            CREATE TABLE IF NOT EXISTS favorites (
                member_id BIGINT NOT NULL,
                content_id BIGINT NOT NULL,
                content_type VARCHAR(20) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY(member_id, content_id, content_type),
                FOREIGN KEY(member_id) REFERENCES members(id)
                ON DELETE CASCADE
            )
            """);
    }

    private long memberId(JwtAuthenticationToken auth) {
        Number id = auth.getToken().getClaim("memberId");
        return id.longValue();
    }

    @GetMapping
    public List<Map<String, Object>> list(
            JwtAuthenticationToken auth) {
        return jdbc.queryForList("""
            SELECT c.id, c.type, c.title, c.rating,
                   c.poster_url, c.ott, c.genre_ids
            FROM favorites f
            JOIN contents c
              ON c.id = f.content_id
              AND c.type = f.content_type
            WHERE f.member_id = ?
              AND c.is_excluded = FALSE
            ORDER BY f.created_at DESC
            """, memberId(auth));
    }

    @PostMapping("/{type}/{id}")
    public Map<String, Object> add(
            @PathVariable("type") String type,
            @PathVariable("id") Long id,
            JwtAuthenticationToken auth) {

        Integer count = jdbc.queryForObject("""
            SELECT COUNT(*) FROM contents
            WHERE id=? AND type=? AND is_excluded=FALSE
            """, Integer.class, id, type);

        if (count == null || count == 0) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND);
        }

        jdbc.update("""
            INSERT INTO favorites(member_id, content_id, content_type)
            VALUES(?,?,?)
            ON DUPLICATE KEY UPDATE content_id=content_id
            """, memberId(auth), id, type);

        return Map.of("favorite", true);
    }

    @DeleteMapping("/{type}/{id}")
    public Map<String, Object> remove(
            @PathVariable("type") String type,
            @PathVariable("id") Long id,
            JwtAuthenticationToken auth) {

        jdbc.update("""
            DELETE FROM favorites
            WHERE member_id=? AND content_id=? AND content_type=?
            """, memberId(auth), id, type);

        return Map.of("favorite", false);
    }
}
