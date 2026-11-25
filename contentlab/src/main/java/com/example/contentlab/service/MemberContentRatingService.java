package com.example.contentlab.service;

import org.springframework.http.HttpStatus;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.util.Set;

@Service
public class MemberContentRatingService {
    private static final Set<String> CONTENT_TYPES = Set.of("movie", "tv", "webtoon");

    private final JdbcTemplate jdbc;

    public MemberContentRatingService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Transactional
    public Integer save(long memberId, String type, long contentId, int rating) {
        validate(type, contentId, rating);
        Integer exists = jdbc.queryForObject("""
                SELECT COUNT(*) FROM contents
                WHERE id=? AND type=? AND is_excluded=FALSE
                """, Integer.class, contentId, type);
        if (exists == null || exists != 1) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "별점을 등록할 콘텐츠를 찾을 수 없습니다.");
        }
        jdbc.update("""
                INSERT INTO member_content_ratings(member_id, content_id, content_type, rating)
                VALUES (?, ?, ?, ?)
                ON DUPLICATE KEY UPDATE rating=VALUES(rating), updated_at=CURRENT_TIMESTAMP(6)
                """, memberId, contentId, type, rating);
        return rating;
    }

    public Integer get(long memberId, String type, long contentId) {
        validate(type, contentId, null);
        return jdbc.query("""
                SELECT rating FROM member_content_ratings
                WHERE member_id=? AND content_type=? AND content_id=?
                """, result -> result.next() ? result.getInt("rating") : null,
                memberId, type, contentId);
    }

    private static void validate(String type, long contentId, Integer rating) {
        if (type == null || !CONTENT_TYPES.contains(type) || contentId <= 0) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "콘텐츠 유형 또는 ID가 올바르지 않습니다.");
        }
        if (rating != null && (rating < 1 || rating > 5)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "별점은 1점부터 5점까지 입력해 주세요.");
        }
    }
}
