package com.example.contentlab;

import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Map;

@RestController
public class ContentController {

    private final JdbcTemplate jdbcTemplate;

    public ContentController(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    @GetMapping("/api/health")
    public Map<String, String> health() {
        return Map.of(
            "status", "success",
            "service", "AI Content Lab"
        );
    }

    @GetMapping("/api/contents")
    public List<Map<String, Object>> getContents() {
        return jdbcTemplate.queryForList(
            "SELECT * FROM contents"
        );
    }

    @GetMapping("/api/contents/count")
    public Map<String, Integer> getCount() {
        Integer count = jdbcTemplate.queryForObject(
            "SELECT COUNT(*) FROM contents",
            Integer.class
        );

        return Map.of("count", count);
    }
}