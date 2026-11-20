package com.example.contentlab.repository;

import java.util.Optional;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;
import jakarta.annotation.PostConstruct;

@Repository
public class MemberRepository {

    private final JdbcTemplate jdbc;

    @Value("${contentlab.schema.init-enabled:true}")
    private boolean initializeSchema = true;

    public MemberRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void init() {
        if (!initializeSchema) {
            return;
        }
        jdbc.execute("""
            CREATE TABLE IF NOT EXISTS members (
                id BIGINT AUTO_INCREMENT PRIMARY KEY,
                email VARCHAR(255) NOT NULL UNIQUE,
                password VARCHAR(255) NOT NULL,
                nickname VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """);
    }

    public record Member(Long id, String email,
                         String password, String nickname) {}

    public void save(String email, String password, String nickname) {
        jdbc.update(
            "INSERT INTO members(email,password,nickname) VALUES(?,?,?)",
            email, password, nickname
        );
    }

    public Optional<Member> findByEmail(String email) {
        return jdbc.query(
            "SELECT id,email,password,nickname FROM members WHERE email=?",
            (rs, n) -> new Member(
                rs.getLong("id"), rs.getString("email"),
                rs.getString("password"), rs.getString("nickname")
            ), email
        ).stream().findFirst();
    }
}
