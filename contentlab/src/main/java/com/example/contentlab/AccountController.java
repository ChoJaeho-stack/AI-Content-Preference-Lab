package com.example.contentlab;

import java.util.Map;
import java.nio.charset.StandardCharsets;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.server.ResponseStatusException;

@RestController
@RequestMapping("/api/me")
public class AccountController {

    private final JdbcTemplate jdbc;
    private final PasswordEncoder encoder;

    public AccountController(JdbcTemplate jdbc, PasswordEncoder encoder) {
        this.jdbc = jdbc;
        this.encoder = encoder;
    }

    private long memberId(JwtAuthenticationToken auth) {
        Number id = auth.getToken().getClaim("memberId");
        return id.longValue();
    }

    @PatchMapping("/nickname")
    public Map<String, Object> updateNickname(
            @RequestBody Map<String, String> data,
            JwtAuthenticationToken auth) {

        String nickname = data.get("nickname");

        if (nickname == null || nickname.isBlank()
                || nickname.trim().length() > 50) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        }

        nickname = nickname.trim();

        jdbc.update(
            "UPDATE members SET nickname=? WHERE id=?",
            nickname, memberId(auth)
        );

        return Map.of("nickname", nickname);
    }

    @PatchMapping("/password")
    public Map<String, Object> updatePassword(
            @RequestBody Map<String, String> data,
            JwtAuthenticationToken auth) {

        String current = data.get("currentPassword");
        String next = data.get("newPassword");
        String confirm = data.get("confirmPassword");

        if (current == null || next == null
                || current.getBytes(StandardCharsets.UTF_8).length > 72
                || next.length() < 8
                || next.getBytes(StandardCharsets.UTF_8).length > 72
                || !next.equals(confirm)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST);
        }

        long id = memberId(auth);

        String saved = jdbc.queryForObject(
            "SELECT password FROM members WHERE id=?",
            String.class, id
        );

        if (!encoder.matches(current, saved)) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED);
        }

        int updated = jdbc.update(
            "UPDATE members SET password=? WHERE id=? AND password=?",
            encoder.encode(next), id, saved
        );

        if (updated == 0) {
            throw new ResponseStatusException(HttpStatus.CONFLICT);
        }

        return Map.of("success", true);
    }
}