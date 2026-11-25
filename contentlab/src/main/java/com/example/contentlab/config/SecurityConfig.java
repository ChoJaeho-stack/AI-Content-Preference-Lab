package com.example.contentlab.config;

import java.util.Base64;
import javax.crypto.spec.SecretKeySpec;
import com.nimbusds.jose.jwk.source.ImmutableSecret;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jwt.*;
import org.springframework.security.oauth2.core.OAuth2Error;
import com.example.contentlab.service.RevokedAuthTokenStore;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.security.oauth2.server.resource.web.BearerTokenResolver;
import org.springframework.security.oauth2.server.resource.web.DefaultBearerTokenResolver;
import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.web.SecurityFilterChain;

@Configuration
public class SecurityConfig {

    @Bean
    public PasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }

    @Bean
    public SecretKeySpec jwtKey(@Value("${JWT_SECRET}") String secret) {
        byte[] key = Base64.getDecoder().decode(secret);
        return new SecretKeySpec(key, "HmacSHA256");
    }

    @Bean
    public JwtEncoder jwtEncoder(SecretKeySpec key) {
        return new NimbusJwtEncoder(new ImmutableSecret<>(key));
    }

    @Bean("jwtSignatureDecoder")
    public JwtDecoder jwtSignatureDecoder(SecretKeySpec key) {
        return NimbusJwtDecoder.withSecretKey(key)
            .macAlgorithm(MacAlgorithm.HS256).build();
    }

    @Bean
    public JwtDecoder jwtDecoder(@Qualifier("jwtSignatureDecoder") JwtDecoder signatureDecoder,
            RevokedAuthTokenStore revokedTokens) {
        return token -> {
            Jwt jwt = signatureDecoder.decode(token);
            try {
                if (revokedTokens.isRevoked(token)) {
                    throw new JwtValidationException("Authentication token has been revoked",
                            java.util.List.of(new OAuth2Error("invalid_token",
                                    "Authentication token has been revoked", null)));
                }
            } catch (RuntimeException unavailable) {
                if (unavailable instanceof JwtValidationException validationFailure) {
                    throw validationFailure;
                }
                // Fail closed if the revocation store cannot be checked.
                throw new JwtValidationException("Authentication validation is unavailable",
                        java.util.List.of(new OAuth2Error("invalid_token",
                                "Authentication validation is unavailable", null)));
            }
            return jwt;
        };
    }

    @Bean
    public SecurityFilterChain securityFilterChain(HttpSecurity http,
            @Qualifier("jwtDecoder") JwtDecoder authenticatedJwtDecoder)
            throws Exception {
        http
            .csrf(csrf -> csrf.disable())
            .formLogin(form -> form.disable())
            .httpBasic(basic -> basic.disable())
            .sessionManagement(session -> session
                .sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .authorizeHttpRequests(auth -> auth
                .requestMatchers(
    "/api/me", "/api/me/**",
    "/api/favorites/**",
    "/api/recommend",
    "/api/history", "/api/history/**"
)
.authenticated()
                .anyRequest().permitAll())
            .oauth2ResourceServer(oauth -> oauth
                .bearerTokenResolver(cookieOrHeaderTokenResolver())
                .jwt(jwt -> jwt.decoder(authenticatedJwtDecoder)));

        return http.build();
    }

    BearerTokenResolver cookieOrHeaderTokenResolver() {
        DefaultBearerTokenResolver headerResolver = new DefaultBearerTokenResolver();
        return request -> {
            String path = request.getServletPath();
            if (path == null || path.isBlank()) {
                path = request.getRequestURI();
                String contextPath = request.getContextPath();
                if (contextPath != null && !contextPath.isBlank() && path.startsWith(contextPath)) {
                    path = path.substring(contextPath.length());
                }
            }
            if (!requiresMemberAuthentication(path) || path.equals("/api/auth/logout")) {
                // A stale browser credential must not block public pages, static assets,
                // catalog APIs, login, or the guest webtoon recommendation endpoint.
                // Logout still clears malformed or expired credentials without decoding them.
                return null;
            }
            Cookie[] cookies = request.getCookies();
            if (cookies != null) {
                for (Cookie cookie : cookies) {
                    if ("CONTENTLAB_AUTH".equals(cookie.getName())
                            && cookie.getValue() != null
                            && !cookie.getValue().isBlank()) {
                        return cookie.getValue();
                    }
                }
            }
            return headerResolver.resolve(request);
        };
    }

    private boolean requiresMemberAuthentication(String path) {
        return path.equals("/api/me") || path.startsWith("/api/me/")
                || path.equals("/api/favorites") || path.startsWith("/api/favorites/")
                || path.equals("/api/recommend")
                || path.equals("/api/history") || path.startsWith("/api/history/");
    }
}
