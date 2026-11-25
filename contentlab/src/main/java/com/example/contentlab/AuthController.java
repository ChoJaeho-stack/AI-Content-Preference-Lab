package com.example.contentlab;

import java.util.Map;
import java.util.HashMap;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseCookie;
import org.springframework.http.ResponseEntity;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtException;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.dao.DataAccessException;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.bind.annotation.*;
import com.example.contentlab.service.AuthService;
import com.example.contentlab.service.RevokedAuthTokenStore;

@RestController
public class AuthController {

    private final AuthService authService;
    private final JwtDecoder jwtDecoder;
    private final RevokedAuthTokenStore revokedTokens;
    private final boolean secureCookie;

    public AuthController(AuthService authService,
            @Qualifier("jwtSignatureDecoder") JwtDecoder jwtDecoder,
            RevokedAuthTokenStore revokedTokens,
            @Value("${contentlab.auth.cookie-secure:false}") boolean secureCookie) {
        this.authService = authService;
        this.jwtDecoder = jwtDecoder;
        this.revokedTokens = revokedTokens;
        this.secureCookie = secureCookie;
    }

    @PostMapping("/api/auth/register")
    @ResponseStatus(HttpStatus.CREATED)
    public Map<String, Object> register(
            @RequestBody Map<String, String> data) {
        return authService.register(data);
    }

    @PostMapping("/api/auth/login")
    public ResponseEntity<Map<String, Object>> login(
            @RequestBody Map<String, String> data) {
        boolean rememberMe = Boolean.parseBoolean(data.getOrDefault("rememberMe", "false"));
        Map<String, Object> session = authService.login(data, rememberMe);
        String token = (String) session.get("token");
        long maxAgeSeconds = (long) session.get("maxAgeSeconds");
        ResponseCookie.ResponseCookieBuilder cookie = ResponseCookie
            .from("CONTENTLAB_AUTH", token)
            .httpOnly(true)
            .secure(secureCookie)
            .sameSite("Lax")
            .path("/");
        if (rememberMe) cookie.maxAge(maxAgeSeconds);
        Map<String, Object> body = new HashMap<>(session);
        body.remove("token");
        body.remove("maxAgeSeconds");
        return ResponseEntity.ok().header("Set-Cookie", cookie.build().toString()).body(body);
    }

    @PostMapping("/api/auth/logout")
    public ResponseEntity<Void> logout(HttpServletRequest request) {
        HttpStatus status = HttpStatus.NO_CONTENT;
        String token = requestToken(request);
        if (token != null) {
            try {
                var decoded = jwtDecoder.decode(token);
                revokedTokens.revoke(token, decoded.getExpiresAt());
            } catch (JwtException invalidOrExpired) {
                // Invalid/expired credentials cannot access anything; still clear the browser cookie.
            } catch (DataAccessException unavailable) {
                // Do not claim server-side revocation succeeded when its store is unavailable.
                status = HttpStatus.SERVICE_UNAVAILABLE;
            }
        }
        ResponseCookie cookie = ResponseCookie.from("CONTENTLAB_AUTH", "")
            .httpOnly(true).secure(secureCookie).sameSite("Lax")
            .path("/").maxAge(0).build();
        return ResponseEntity.status(status).header("Set-Cookie", cookie.toString()).build();
    }

    private static String requestToken(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies != null) {
            for (Cookie cookie : cookies) {
                if ("CONTENTLAB_AUTH".equals(cookie.getName()) && !cookie.getValue().isBlank()) {
                    return cookie.getValue();
                }
            }
        }
        String authorization = request.getHeader("Authorization");
        return authorization != null && authorization.startsWith("Bearer ")
                ? authorization.substring(7) : null;
    }

    @GetMapping("/api/me")
    public Map<String, Object> me(JwtAuthenticationToken auth) {
        return Map.of(
            "email", auth.getName(),
            "memberId", auth.getToken().getClaim("memberId")
        );
    }
}
