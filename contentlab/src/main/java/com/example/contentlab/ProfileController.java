package com.example.contentlab;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.*;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import java.util.*;

@RestController
public class ProfileController {

    private final JdbcTemplate jdbc;

    public ProfileController(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @GetMapping("/api/me/stats")
    public Map<String, Object> stats(JwtAuthenticationToken auth) {

        Number memberId = auth.getToken().getClaim("memberId");
        long id = memberId.longValue();

        Long favoriteCount = jdbc.queryForObject(
            "SELECT COUNT(*) FROM favorites WHERE member_id=?",
            Long.class, id
        );

        Long historyCount = jdbc.queryForObject(
            "SELECT COUNT(*) FROM recommendation_history WHERE member_id=?",
            Long.class, id
        );

        List<Map<String, Object>> preferences = jdbc.queryForList(
            """
            SELECT
                CASE
                    WHEN c.type = 'movie' THEN 'movie'
                    WHEN c.type = 'tv' AND (
                        JSON_CONTAINS(c.genre_ids, '10764')
                        OR JSON_CONTAINS(c.genre_ids, '10767')
                    ) THEN 'variety'
                    WHEN c.type = 'tv' AND (
                        JSON_CONTAINS(c.genre_ids, '18')
                        OR JSON_CONTAINS(c.genre_ids, '10766')
                    ) THEN 'drama'
                    ELSE c.type
                END AS type,
                COUNT(*) AS count
            FROM favorites f
            JOIN contents c
                ON f.content_id = c.id
                AND f.content_type = c.type
            WHERE f.member_id=?
            GROUP BY 1
            ORDER BY count DESC
            """, id
        );

        Map<String, Object> result = new LinkedHashMap<>();
        result.put("email", auth.getName());
        result.put("nickname", jdbc.queryForObject(
            "SELECT nickname FROM members WHERE id=?",
            String.class, id
        ));
        result.put("memberId", id);
        result.put("favoriteCount", favoriteCount);
        result.put("historyCount", historyCount);
        result.put("preferences", preferences);

        List<Map<String, Object>> genres = jdbc.queryForList(
            """
            SELECT g.genre_id AS genreId, COUNT(DISTINCT c.id, c.type) AS count
            FROM favorites f
            JOIN contents c
                ON f.content_id = c.id
                AND f.content_type = c.type
            JOIN JSON_TABLE(
                c.genre_ids,
                '$[*]' COLUMNS (genre_id INT PATH '$')
            ) AS g ON TRUE
            WHERE f.member_id=?
            GROUP BY g.genre_id
            ORDER BY count DESC, g.genre_id ASC
            LIMIT 5
            """, id
        );

        result.put("genres", genres);

        return result;
    }
}