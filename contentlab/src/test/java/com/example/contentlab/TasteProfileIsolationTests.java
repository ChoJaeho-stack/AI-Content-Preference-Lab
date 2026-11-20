package com.example.contentlab;

import com.example.contentlab.service.TasteProfileService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.server.ResponseStatusException;

import java.util.Map;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.Mockito.*;
import static org.springframework.http.HttpStatus.SERVICE_UNAVAILABLE;

class TasteProfileIsolationTests {
    @Test
    void profileWriteLocksMemberBeforeReadingSchemaMetadata() {
        var jdbc = mock(JdbcTemplate.class);
        var service = new TasteProfileService(jdbc);
        when(jdbc.query(contains("FOR UPDATE"),
                org.mockito.ArgumentMatchers.<ResultSetExtractor<Boolean>>any(), eq(11L))).thenReturn(true);
        when(jdbc.queryForObject(contains("information_schema.tables"), eq(Integer.class))).thenReturn(0);

        var error = assertThrows(ResponseStatusException.class, () -> service.saveSurvey(11L, Map.of()));
        assertEquals(SERVICE_UNAVAILABLE, error.getStatusCode());

        var ordered = inOrder(jdbc);
        ordered.verify(jdbc).query(contains("FOR UPDATE"),
                org.mockito.ArgumentMatchers.<ResultSetExtractor<Boolean>>any(), eq(11L));
        ordered.verify(jdbc).queryForObject(contains("information_schema.tables"), eq(Integer.class));
        verifyNoMoreInteractions(jdbc);
    }

    @Test
    void surveyAndFeedbackAlwaysUseAuthenticatedMemberId() {
        var service = mock(TasteProfileService.class);
        var controller = new TasteProfileController(service);
        var memberA = auth(11L);
        var memberB = auth(22L);
        when(service.getProfile(11L)).thenReturn(Map.of("member", "A"));
        when(service.getProfile(22L)).thenReturn(Map.of("member", "B"));

        assertEquals("A", controller.getTaste(memberA).get("member"));
        assertEquals("B", controller.getTaste(memberB).get("member"));
        verify(service).getProfile(11L);
        verify(service).getProfile(22L);
        var survey = Map.<String, Object>of("genres", java.util.List.of("fantasy"));
        controller.saveSurvey(survey, memberA);
        controller.saveFeedback(new TasteProfileController.FeedbackRequest("webtoon", 501L, -1), memberB);

        verify(service).saveSurvey(11L, survey);
        verify(service).saveFeedback(22L, "webtoon", 501L, -1);
        verifyNoMoreInteractions(service);
    }

    private static JwtAuthenticationToken auth(long memberId) {
        return new JwtAuthenticationToken(Jwt.withTokenValue("test-token")
                .header("alg", "HS256")
                .claim("memberId", memberId)
                .build());
    }
}
