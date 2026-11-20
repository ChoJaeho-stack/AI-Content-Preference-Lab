package com.example.contentlab;

import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.*;
import com.example.contentlab.service.AuthService;

@RestController
public class AuthController {

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/api/auth/register")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> register(
            @RequestBody Map<String, String> data) {
        return authService.register(data);
    }

    @PostMapping("/api/auth/login")
    public Map<String, Object> login(
            @RequestBody Map<String, String> data) {
        return authService.login(data);
    }

    @GetMapping("/api/me")
    public Map<String, Object> me(JwtAuthenticationToken auth) {
        return Map.of(
            "email", auth.getName(),
            "memberId", auth.getToken().getClaim("memberId")
        );
    }
}