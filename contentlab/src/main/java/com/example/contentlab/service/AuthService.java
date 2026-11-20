package com.example.contentlab.service;

import java.time.Instant;
import java.util.Locale;
import java.util.Map;
import java.nio.charset.StandardCharsets;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;
import com.example.contentlab.repository.MemberRepository;

@Service
public class AuthService {

    private final MemberRepository members;
    private final PasswordEncoder encoder;
    private final JwtEncoder jwtEncoder;

    public AuthService(MemberRepository members,
                       PasswordEncoder encoder,
                       JwtEncoder jwtEncoder) {
        this.members = members;
        this.encoder = encoder;
        this.jwtEncoder = jwtEncoder;
    }

    public Map<String, Object> register(Map<String, String> data) {
        String email = data.getOrDefault("email", "").trim()
            .toLowerCase(Locale.ROOT);
        String password = data.getOrDefault("password", "");
        String nickname = data.getOrDefault("nickname", "").trim();

        if (!email.matches("^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$")
                || email.length() > 255
                || password.length() < 8
                || password.getBytes(StandardCharsets.UTF_8).length > 72
                || nickname.isBlank() || nickname.length() > 50) {
            throw new ResponseStatusException(
                HttpStatus.BAD_REQUEST, "Invalid registration data");
        }

        try {
            members.save(email, encoder.encode(password), nickname);
        } catch (DuplicateKeyException e) {
            throw new ResponseStatusException(
                HttpStatus.CONFLICT, "Email already exists");
        }

        return Map.of("message", "Registration successful");
    }

    public Map<String, Object> login(Map<String, String> data) {
        String email = data.getOrDefault("email", "").trim()
            .toLowerCase(Locale.ROOT);
        String password = data.getOrDefault("password", "");

        var member = members.findByEmail(email)
            .orElseThrow(() -> new ResponseStatusException(
                HttpStatus.UNAUTHORIZED, "Invalid credentials"));

        if (password.getBytes(StandardCharsets.UTF_8).length > 72
                || !encoder.matches(password, member.password())) {
            throw new ResponseStatusException(
                HttpStatus.UNAUTHORIZED, "Invalid credentials");
        }

        Instant now = Instant.now();

        var claims = JwtClaimsSet.builder()
            .subject(member.email())
            .issuedAt(now)
            .expiresAt(now.plusSeconds(3600))
            .claim("memberId", member.id())
            .build();

        var header = JwsHeader.with(MacAlgorithm.HS256).build();
        String token = jwtEncoder.encode(
            JwtEncoderParameters.from(header, claims)
        ).getTokenValue();

        return Map.of(
            "token", token,
            "nickname", member.nickname(),
            "email", member.email()
        );
    }
}