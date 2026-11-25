package com.example.contentlab.config;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNull;

import jakarta.servlet.http.Cookie;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.security.oauth2.server.resource.web.BearerTokenResolver;

class SecurityConfigTests {
    private final BearerTokenResolver resolver = new SecurityConfig().cookieOrHeaderTokenResolver();

    @Test
    void ignoresStaleCredentialsOnPublicPageStaticAndGuestRoutes() {
        for (String path : new String[] {
                "/", "/index.html", "/contentlab-ui.css", "/webtoon-official-links.js",
                "/api/health", "/api/contents", "/api/webtoons/recommend",
                "/api/auth/login", "/api/auth/register", "/api/auth/logout"}) {
            MockHttpServletRequest request = new MockHttpServletRequest("GET", path);
            request.setServletPath(path);
            request.setCookies(new Cookie("CONTENTLAB_AUTH", "expired-or-malformed"));
            request.addHeader("Authorization", "Bearer expired-or-malformed");

            assertNull(resolver.resolve(request), "Public request must ignore stale credentials: " + path);
        }
    }

    @Test
    void stillResolvesCookieAndBearerCredentialsForMemberRoutes() {
        for (String path : new String[] {
                "/api/me", "/api/me/taste", "/api/favorites", "/api/favorites/movie/1",
                "/api/recommend", "/api/history", "/api/history/1"}) {
            MockHttpServletRequest cookieRequest = new MockHttpServletRequest("GET", path);
            cookieRequest.setServletPath(path);
            cookieRequest.setCookies(new Cookie("CONTENTLAB_AUTH", "member-cookie"));
            assertEquals("member-cookie", resolver.resolve(cookieRequest),
                    "Member cookie authentication must remain enabled: " + path);

            MockHttpServletRequest headerRequest = new MockHttpServletRequest("GET", path);
            headerRequest.setServletPath(path);
            headerRequest.addHeader("Authorization", "Bearer member-header");
            assertEquals("member-header", resolver.resolve(headerRequest),
                    "Member bearer authentication must remain enabled: " + path);
        }
    }

    @Test
    void resolvesMemberCredentialsWhenServletPathIsUnavailable() {
        MockHttpServletRequest request = new MockHttpServletRequest();
        request.setRequestURI("/api/favorites/movie/1");
        request.addHeader("Authorization", "Bearer member-header");

        assertEquals("member-header", resolver.resolve(request));
    }
}
