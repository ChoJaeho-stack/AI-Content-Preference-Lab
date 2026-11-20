package com.example.contentlab;

import java.sql.DriverManager;
import java.sql.SQLException;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import javax.sql.DataSource;

import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.SingleConnectionDataSource;
import org.springframework.security.web.FilterChainProxy;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.setup.MockMvcBuilders;
import org.springframework.web.context.WebApplicationContext;
import tools.jackson.databind.json.JsonMapper;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertTrue;

@EnabledIfEnvironmentVariable(named = "CONTENTLAB_RECOMMEND_E2E", matches = "true")
@SpringBootTest(properties = {"spring.jpa.hibernate.ddl-auto=none", "spring.sql.init.mode=never"})
@Import(RecommendationEndToEndTests.FixtureDatabase.class)
class RecommendationEndToEndTests {
    private static final JsonMapper JSON = JsonMapper.builder().build();

    @DynamicPropertySource
    static void testJwtKey(DynamicPropertyRegistry properties) {
        properties.add("JWT_SECRET", () -> Base64.getEncoder().encodeToString(new byte[32]));
    }

    @Test
    void realMembersGetSeparateRecommendationsAndCanOnlyAccessTheirOwnHistory(
            @Autowired WebApplicationContext context, @Autowired FilterChainProxy security) throws Exception {
        MockMvc mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(security).build();
        String firstToken = createMember(mvc, "comedy");
        String secondToken = createMember(mvc, "horror");
        mvc.perform(post("/api/recommend")).andExpect(status().isUnauthorized());
        mvc.perform(post("/api/favorites/movie/1").header("Authorization", bearer(firstToken)))
                .andExpect(status().isOk());
        mvc.perform(post("/api/favorites/movie/2").header("Authorization", bearer(secondToken)))
                .andExpect(status().isOk());
        mvc.perform(post("/api/favorites/movie/3").header("Authorization", bearer(firstToken)))
                .andExpect(status().isOk());
        mvc.perform(get("/api/favorites").header("Authorization", bearer(firstToken)))
                .andExpect(jsonPath("$.length()").value(2));
        mvc.perform(get("/api/favorites").header("Authorization", bearer(secondToken)))
                .andExpect(jsonPath("$.length()").value(1)).andExpect(jsonPath("$[0].id").value(2));
        var stats = JSON.readTree(mvc.perform(get("/api/me/stats").header("Authorization", bearer(firstToken)))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        var genreIds = new ArrayList<Integer>();
        for (var genre : stats.path("genres")) {
            genreIds.add(genre.path("genreId").asInt());
        }
        assertEquals(List.of(35, 12, 14, 16, 18), genreIds);

        recommend(mvc, firstToken).andExpect(jsonPath("$.recommendations[0].id").value(11))
                .andExpect(jsonPath("$.taste_analysis").value("recent:"));
        recommend(mvc, secondToken).andExpect(jsonPath("$.recommendations[0].id").value(12))
                .andExpect(jsonPath("$.taste_analysis").value("recent:"));
        recommend(mvc, firstToken).andExpect(jsonPath("$.taste_analysis").value("recent:11"));

        long secondHistory = JSON.readTree(mvc.perform(get("/api/history")
                        .header("Authorization", bearer(secondToken)))
                .andExpect(status().isOk()).andExpect(jsonPath("$.length()").value(1))
                .andReturn().getResponse().getContentAsString()).get(0).get("id").asLong();
        mvc.perform(get("/api/history").header("Authorization", bearer(firstToken)))
                .andExpect(jsonPath("$.length()").value(2));
        mvc.perform(delete("/api/history/{id}", secondHistory).header("Authorization", bearer(firstToken)))
                .andExpect(status().isNotFound());
        mvc.perform(get("/api/history").header("Authorization", bearer(secondToken)))
                .andExpect(jsonPath("$[0].id").value(secondHistory));
    }

    @Test
    @EnabledIfEnvironmentVariable(named = "CONTENTLAB_RECOMMEND_LIVE_GEMINI", matches = "true")
    void liveGeminiRecommendationIsSaved(@Autowired WebApplicationContext context,
            @Autowired FilterChainProxy security, @Autowired JdbcTemplate jdbc) throws Exception {
        var mvc = MockMvcBuilders.webAppContextSetup(context).addFilters(security).build();
        String token = createMember(mvc, "live-fixture");
        mvc.perform(post("/api/favorites/movie/3").header("Authorization", bearer(token)))
                .andExpect(status().isOk());
        assertEquals(1, jdbc.update("""
                INSERT INTO recommendation_history (member_id, result, created_at)
                SELECT id, ?, CURRENT_TIMESTAMP(6) FROM members WHERE email = ?
                """, "{\"recommendations\":[{\"id\":1,\"type\":\"movie\"}]}", "live-fixture@e2e.invalid"));

        var response = JSON.readTree(mvc.perform(post("/api/recommend")
                        .header("Authorization", bearer(token)).contentType(MediaType.APPLICATION_JSON)
                        .content(JSON.writeValueAsString(Map.of(
                                "taste", "코미디 영화 추천", "liked", "Second comedy favorite, 코미디",
                                "disliked", "공포", "preference", "영화"))))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        var recommendations = response.path("recommendations");
        assertTrue(recommendations.isArray() && !recommendations.isEmpty(), "expected a recommendation");
        for (var recommendation : recommendations) {
            assertTrue(List.of(1L, 11L).contains(recommendation.path("id").asLong()));
        }
        var history = JSON.readTree(mvc.perform(get("/api/history").header("Authorization", bearer(token)))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString());
        assertEquals(2, history.size());
        assertEquals(response, JSON.readTree(history.get(0).path("result").asString()));
    }

    private static String createMember(MockMvc mvc, String nickname) throws Exception {
        var credentials = Map.of("email", nickname + "@e2e.invalid", "nickname", nickname,
                "password", UUID.randomUUID().toString());
        String body = JSON.writeValueAsString(credentials);
        mvc.perform(post("/api/auth/register").contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isCreated());
        return JSON.readTree(mvc.perform(post("/api/auth/login")
                        .contentType(MediaType.APPLICATION_JSON).content(body))
                .andExpect(status().isOk()).andReturn().getResponse().getContentAsString())
                .get("token").asString();
    }

    private static ResultActions recommend(MockMvc mvc, String token) throws Exception {
        return mvc.perform(post("/api/recommend").header("Authorization", bearer(token))
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{\"taste\":\"recommend a movie\"}"))
                .andExpect(status().isOk());
    }

    private static String bearer(String token) {
        return "Bearer " + token;
    }

    @TestConfiguration(proxyBeanMethods = false)
    static class FixtureDatabase {
        @Bean
        SingleConnectionDataSource fixtureDataSource(
                @Value("${spring.datasource.url}") String url,
                @Value("${spring.datasource.username}") String user,
                @Value("${spring.datasource.password}") String password) throws SQLException {
            var connection = DriverManager.getConnection(url, user, password);
            try (var statement = connection.createStatement()) {
                for (String sql : List.of("""
                        CREATE TEMPORARY TABLE members (
                          id BIGINT AUTO_INCREMENT PRIMARY KEY, email VARCHAR(255) UNIQUE NOT NULL,
                          password VARCHAR(255) NOT NULL, nickname VARCHAR(50) NOT NULL)
                        """, """
                        CREATE TEMPORARY TABLE contents (
                          id BIGINT, type VARCHAR(20), title VARCHAR(255), genre_ids JSON,
                          rating DOUBLE DEFAULT 8, poster_url VARCHAR(255), ott JSON,
                          is_excluded BOOLEAN DEFAULT FALSE, PRIMARY KEY (id, type))
                        """, """
                        CREATE TEMPORARY TABLE favorites (
                          member_id BIGINT, content_id BIGINT, content_type VARCHAR(20),
                          created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                          PRIMARY KEY (member_id, content_id, content_type))
                        """, """
                        CREATE TEMPORARY TABLE recommendation_history (
                          id BIGINT AUTO_INCREMENT PRIMARY KEY, member_id BIGINT NOT NULL,
                          liked TEXT, disliked TEXT, preference VARCHAR(255), result JSON NOT NULL,
                          created_at DATETIME(6) NOT NULL)
                        """, """
                        INSERT INTO contents (id, type, title, genre_ids, ott) VALUES
                          (1, 'movie', 'Comedy favorite', '[12,14,16,18,28,35]', '[]'),
                          (2, 'movie', 'Horror favorite', '[27]', '[]'),
                          (3, 'movie', 'Second comedy favorite', '[35]', '[]'),
                          (11, 'movie', 'Comedy candidate', '[35]', '[]'),
                          (12, 'movie', 'Horror candidate', '[27]', '[]')
                        """)) {
                    statement.execute(sql);
                }
                return new SingleConnectionDataSource(connection, true);
            } catch (SQLException error) {
                connection.close();
                throw error;
            }
        }

        @Bean
        JdbcTemplate jdbcTemplate(DataSource dataSource) {
            return new JdbcTemplate(dataSource) {
                @Override
                public void execute(String sql) {
                    // Startup tables are already shadowed by this connection's fixtures.
                    String ddl = sql.stripLeading();
                    if (!ddl.startsWith("CREATE TABLE IF NOT EXISTS members (")
                            && !ddl.startsWith("CREATE TABLE IF NOT EXISTS favorites (")) {
                        super.execute(sql);
                    }
                }
            };
        }
    }
}
