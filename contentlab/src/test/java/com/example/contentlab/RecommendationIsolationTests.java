package com.example.contentlab;

import com.example.contentlab.entity.RecommendationHistory;
import com.example.contentlab.repository.ContentRepository;
import com.example.contentlab.repository.RecommendationHistoryRepository;
import com.example.contentlab.service.ContentService;
import com.example.contentlab.service.CatalogCache;
import com.example.contentlab.service.AiRecommendationClient;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.ResultSetExtractor;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.http.MediaType;
import org.springframework.security.oauth2.jwt.Jwt;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.json.JsonMapper;

import java.util.List;
import java.util.Map;
import java.net.URI;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.ArgumentMatchers.*;
import static org.mockito.Mockito.*;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.*;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

class RecommendationIsolationTests {
    @Test
    void guestWebtoonPreviewUsesOnlyCurrentSurveyAndNeverLoadsOrSavesMemberData() {
        var jdbc = mock(JdbcTemplate.class);
        var histories = mock(RecommendationHistoryRepository.class);
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var endpoint = URI.create("http://127.0.0.1:8000/recommend");
        var controller = new ContentController(
                new ContentService(mock(ContentRepository.class), histories, jdbc,
                        new AiRecommendationClient(endpoint, builder.build())),
                mock(CatalogCache.class));
        when(jdbc.queryForObject(contains("information_schema.tables"), eq(Integer.class))).thenReturn(5);
        server.expect(requestTo(endpoint))
                .andExpect(content().json("""
                        {"taste":"guest","contentType":"webtoon","publicPreview":true,
                         "tasteProfile":{"dimensions":{"genres":{"fantasy":1.0},"story":{},"mood":{},"pacing":{}}}}
                        """, org.springframework.test.json.JsonCompareMode.STRICT))
                .andRespond(withSuccess("{\"taste_analysis\":\"preview\",\"recommendations\":[]}", MediaType.APPLICATION_JSON));

        assertEquals("preview", controller.recommendWebtoonGuest(Map.of(
                "taste", "guest", "survey", Map.of("genres", List.of(" Fantasy ", "fantasy")),
                "memberId", 12, "contentType", "movie", "tasteProfile", Map.of("spoofed", true)
        )).get("taste_analysis"));
        server.verify();
        verify(jdbc).queryForObject(contains("information_schema.tables"), eq(Integer.class));
        verifyNoMoreInteractions(jdbc);
        verifyNoInteractions(histories);
    }

    @Test
    void sendsStoredWebtoonTasteAndReturnsFiveRankedCardsInUpstreamOrder() {
        var jdbc = mock(JdbcTemplate.class);
        var histories = mock(RecommendationHistoryRepository.class);
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var endpoint = URI.create("http://127.0.0.1:8000/recommend");
        var controller = new ContentController(
                new ContentService(mock(ContentRepository.class), histories, jdbc,
                        new AiRecommendationClient(endpoint, builder.build())),
                mock(CatalogCache.class));
        when(jdbc.queryForObject(contains("information_schema.tables"), eq(Integer.class))).thenReturn(5);
        when(jdbc.query(contains("FROM member_taste_profiles WHERE member_id=?"),
                org.mockito.ArgumentMatchers.<ResultSetExtractor<String>>any(), eq(11L)))
                .thenReturn("{\"dimensions\":{\"genres\":{\"fantasy\":1}}}");
        stubFavorites(jdbc, 11L, List.of());
        stubGenres(jdbc, 11L, List.of());
        when(histories.findTop20ByMemberIdOrderByCreatedAtDesc(11L)).thenReturn(List.of());

        var json = JsonMapper.builder().build();
        var rankedIds = List.of(9, 2, 5, 3, 1);
        var cards = rankedIds.stream()
                .map(id -> Map.of("id", id, "type", "webtoon", "title", "Fixture " + id,
                        "match_score", 80, "personal_fit_score", 80, "reason", "Fantasy preference"))
                .toList();
        var upstream = Map.of("taste_analysis", "Fantasy", "recommendations", cards);
        server.expect(requestTo(endpoint))
                .andExpect(content().json("""
                        {"taste":"fantasy","contentType":"webtoon","favorites":[],"preferredGenres":[],
                         "recentHistory":[],"tasteProfile":{"dimensions":{"genres":{"fantasy":1}}}}
                        """, org.springframework.test.json.JsonCompareMode.STRICT))
                .andRespond(withSuccess(json.writeValueAsString(upstream), MediaType.APPLICATION_JSON));

        var jwt = Jwt.withTokenValue("unit-test").header("alg", "HS256").claim("memberId", 11L).build();
        var result = controller.recommend(Map.of("taste", "fantasy", "contentType", "webtoon",
                "memberId", "22", "tasteProfile", "spoofed"), new JwtAuthenticationToken(jwt));
        assertEquals(json.valueToTree(upstream), json.valueToTree(result));
        var saved = ArgumentCaptor.forClass(RecommendationHistory.class);
        verify(histories).save(saved.capture());
        assertEquals(11L, saved.getValue().getMemberId());
        assertEquals(json.valueToTree(upstream), json.readTree(saved.getValue().getResult()));
        server.verify();
    }

    @Test
    void sendsOnlyAuthenticatedMembersProfileAndStoresResultsUnderSameIdentity() {
        var jdbc = mock(JdbcTemplate.class);
        var histories = mock(RecommendationHistoryRepository.class);
        var builder = RestClient.builder();
        var server = MockRestServiceServer.bindTo(builder).build();
        var controller = new ContentController(
                new ContentService(mock(ContentRepository.class), histories, jdbc,
                        new AiRecommendationClient(URI.create("http://127.0.0.1:8000/recommend"), builder.build())),
                mock(CatalogCache.class));

        stubFavorites(jdbc, 11L, List.of(Map.of("id", 7, "type", "movie", "title", "first")));
        stubFavorites(jdbc, 22L, List.of(Map.of("id", 7, "type", "tv", "title", "second")));
        stubFavorites(jdbc, 33L, List.of());
        stubGenres(jdbc, 11L, List.of(35));
        stubGenres(jdbc, 22L, List.of(27));
        stubGenres(jdbc, 33L, List.of());
        when(histories.findTop20ByMemberIdOrderByCreatedAtDesc(11L)).thenReturn(List.of(
                history(11L, "malformed"),
                history(11L, """
                        {"recommendations":[{"id":7,"type":"movie"},{"id":"7","type":"movie"}]}
                        """)));
        when(histories.findTop20ByMemberIdOrderByCreatedAtDesc(22L)).thenReturn(List.of(
                history(22L, "\"{\\\"recommendations\\\":[{\\\"id\\\":\\\"7\\\",\\\"type\\\":\\\"tv\\\"}]}\"")));
        when(histories.findTop20ByMemberIdOrderByCreatedAtDesc(33L)).thenReturn(List.of());

        expectProfile(server, """
                {"taste":"recommend","favorites":[{"id":7,"type":"movie","title":"first"}],
                "preferredGenres":[35],"recentHistory":["movie:7"]}
                """);
        expectProfile(server, """
                {"taste":"recommend","favorites":[{"id":7,"type":"tv","title":"second"}],
                "preferredGenres":[27],"recentHistory":["tv:7"]}
                """);
        expectProfile(server, """
                {"taste":"recommend","favorites":[],"preferredGenres":[],"recentHistory":[]}
                """);
        var request = Map.of("taste", "recommend", "memberId", "22",
                "favorites", "spoofed", "preferredGenres", "spoofed", "recentHistory", "spoofed");
        for (long id : List.of(11L, 22L, 33L)) {
            var jwt = Jwt.withTokenValue("unit-test").header("alg", "HS256")
                    .claim("memberId", id).build();
            controller.recommend(request, new JwtAuthenticationToken(jwt));
            verify(histories).findTop20ByMemberIdOrderByCreatedAtDesc(id);
        }
        var saved = ArgumentCaptor.forClass(RecommendationHistory.class);
        verify(histories, times(3)).save(saved.capture());
        assertEquals(List.of(11L, 22L, 33L),
                saved.getAllValues().stream().map(RecommendationHistory::getMemberId).toList());
        server.verify();
    }

    private static void stubFavorites(JdbcTemplate jdbc, long id, List<Map<String, Object>> rows) {
        when(jdbc.query(contains("WHERE f.member_id = ?"),
                org.mockito.ArgumentMatchers.<RowMapper<Map<String, Object>>>any(), eq(id)))
                .thenReturn(rows);
    }

    private static void stubGenres(JdbcTemplate jdbc, long id, List<Integer> genres) {
        when(jdbc.queryForList(contains("WHERE f.member_id = ?"), eq(Integer.class), eq(id)))
                .thenReturn(genres);
    }

    private static RecommendationHistory history(long id, String result) {
        return new RecommendationHistory(id, null, null, null, result);
    }

    private static void expectProfile(MockRestServiceServer server, String payload) {
        server.expect(requestTo("http://127.0.0.1:8000/recommend"))
                .andExpect(content().json(payload, org.springframework.test.json.JsonCompareMode.STRICT))
                .andRespond(withSuccess("{\"taste_analysis\":\"\",\"recommendations\":[]}", MediaType.APPLICATION_JSON));
    }
}
