package com.example.contentlab.service;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.server.ResponseStatusException;

import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

/** Keeps unfinished webtoon schema rollout from surfacing as an opaque DB error. */
public final class WebtoonSchemaGuard {
    private static final int REQUIRED_TABLE_COUNT = 5;

    private WebtoonSchemaGuard() {}

    public static void requireReady(JdbcTemplate jdbc) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema=DATABASE()
                  AND table_name IN ('content_external_ids', 'webtoon_metadata',
                                     'member_taste_surveys', 'member_content_feedback',
                                     'member_taste_profiles')
                """, Integer.class);
        if (count == null || count != REQUIRED_TABLE_COUNT) {
            throw new ResponseStatusException(SERVICE_UNAVAILABLE,
                    "웹툰 기능용 데이터베이스 구조가 아직 준비되지 않았습니다.");
        }
    }
}
