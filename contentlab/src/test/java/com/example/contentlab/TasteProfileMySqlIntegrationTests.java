package com.example.contentlab;

import com.example.contentlab.service.TasteProfileService;
import com.example.contentlab.service.WebtoonSchemaGuard;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.condition.EnabledIfEnvironmentVariable;
import org.springframework.context.annotation.AnnotationConfigApplicationContext;
import org.springframework.context.annotation.Configuration;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.datasource.DataSourceTransactionManager;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.transaction.annotation.EnableTransactionManagement;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.json.JsonMapper;

import java.util.List;
import java.util.Map;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.TimeoutException;

import static org.junit.jupiter.api.Assertions.*;

@EnabledIfEnvironmentVariable(named = "CONTENTLAB_TASTE_MYSQL_TEST", matches = "true")
class TasteProfileMySqlIntegrationTests {
    private static final String SCHEMA = "contentlab_taste_test";
    private static final String JDBC_URL = "jdbc:mysql://127.0.0.1:13306/" + SCHEMA
            + "?connectTimeout=3000&socketTimeout=10000";
    private static final JsonMapper JSON = JsonMapper.builder().build();

    @Test
    void persistsMemberProfilesThroughFeedbackDeletionAndConcurrentUpdates() throws Exception {
        String password = System.getenv("CONTENTLAB_TASTE_MYSQL_PASSWORD");
        assertTrue(password != null && !password.isBlank(), "Dedicated test password is required");
        var dataSource = new DriverManagerDataSource(JDBC_URL, "contentlab_taste_test", password);
        var jdbc = new JdbcTemplate(dataSource);
        var transactionManager = new DataSourceTransactionManager(dataSource);

        assertEquals(SCHEMA, jdbc.queryForObject("SELECT DATABASE()", String.class));
        WebtoonSchemaGuard.requireReady(jdbc);
        for (String table : List.of("members", "contents", "content_external_ids", "webtoon_metadata",
                "member_taste_surveys", "member_content_feedback", "member_taste_profiles")) {
            assertEquals(0L, jdbc.queryForObject("SELECT COUNT(*) FROM " + table, Long.class),
                    "Run only in a fresh disposable schema. Nonempty table: " + table);
        }

        try (var context = new AnnotationConfigApplicationContext()) {
            context.registerBean(JdbcTemplate.class, () -> jdbc);
            context.registerBean(DataSourceTransactionManager.class, () -> transactionManager);
            context.register(TransactionConfig.class, TasteProfileService.class);
            context.refresh();

            var transactions = new TransactionTemplate(transactionManager);
            transactions.executeWithoutResult(status -> seed(jdbc));
            var service = context.getBean(TasteProfileService.class);
            verifyWeightsAndDeletion(service, jdbc);
            verifyConcurrentUpdates(service, jdbc, transactions);
        }
    }

    private static void seed(JdbcTemplate jdbc) {
        for (long member : List.of(11L, 22L, 33L)) {
            jdbc.update("INSERT INTO members(id, email, nickname, password) VALUES (?, ?, ?, ?)",
                    member, member + "@example.invalid", "Fixture " + member, "disabled-fixture");
        }
        jdbc.update("INSERT INTO contents(id, type, title, is_excluded) VALUES (501, 'movie', 'Fixture movie', FALSE)");
        insertWebtoon(jdbc, 501L, "[\"FANTASY\",\" fantasy \", \"mystery\"]");
        insertWebtoon(jdbc, 502L, "[\"fantasy\",\"neutral-only\"]");
    }

    private static void insertWebtoon(JdbcTemplate jdbc, long id, String genres) {
        jdbc.update("INSERT INTO contents(id, type, title, is_excluded) VALUES (?, 'webtoon', ?, FALSE)",
                id, "Fixture webtoon " + id);
        jdbc.update("""
                INSERT INTO content_external_ids(provider_code, external_id, content_type, content_id)
                VALUES ('fixture', ?, 'webtoon', ?)
                """, Long.toString(id), id);
        jdbc.update("""
                INSERT INTO webtoon_metadata(content_id, service_platform, source_provider, genre_tags,
                                             story_tags, mood_tags, pacing)
                VALUES (?, 'fixture', 'fixture', ?, '["quest"]', '["calm"]', 'fast')
                """, id, genres);
    }

    private static void verifyWeightsAndDeletion(TasteProfileService service, JdbcTemplate jdbc) {
        service.saveSurvey(11L, Map.of("genres", List.of(" Fantasy ", "fantasy"), "story", "quest",
                "mood", "calm", "pacing", "fast"));
        service.saveSurvey(22L, Map.of("genres", "romance"));
        service.saveFeedback(11L, "webtoon", 501L, -1);
        service.saveFeedback(22L, "webtoon", 501L, 1);

        var beforeNeutral = service.getProfile(11L);
        var memberA = JSON.valueToTree(beforeNeutral);
        assertEquals(JSON.readTree("[\"fantasy\"]"), memberA.at("/survey/genres"));
        assertEquals(JSON.readTree("""
                {"genres":{"fantasy":-0.5,"mystery":-1.0},"story":{"quest":-0.5},
                 "mood":{"calm":-0.5},"pacing":{"fast":-0.5}}
                """), memberA.at("/profile/dimensions"));
        var memberBBefore = service.getProfile(22L);
        assertEquals(JSON.readTree("{\"fantasy\":1.0,\"mystery\":1.0,\"romance\":1.0}"),
                JSON.valueToTree(memberBBefore).at("/profile/dimensions/genres"));
        int memberBRevision = revision(jdbc, 22L);

        service.saveFeedback(11L, "webtoon", 502L, 0);
        assertEquals(0, rating(jdbc, 11L, 502L));
        assertEquals(beforeNeutral, service.getProfile(11L));
        service.deleteFeedback(11L, "webtoon", 501L);

        var afterDelete = JSON.valueToTree(service.getProfile(11L));
        assertEquals(memberA.at("/survey"), afterDelete.at("/survey"));
        assertEquals(JSON.readTree("""
                {"genres":{"fantasy":1.0},"story":{"quest":1.0},"mood":{"calm":1.0},"pacing":{"fast":1.0}}
                """), afterDelete.at("/profile/dimensions"));
        assertEquals(0L, jdbc.queryForObject("""
                SELECT COUNT(*) FROM member_content_feedback
                WHERE member_id=11 AND content_id=501 AND content_type='webtoon'
                """, Long.class));
        assertEquals(0, rating(jdbc, 11L, 502L));
        assertEquals(1, rating(jdbc, 22L, 501L));
        assertEquals(memberBBefore, service.getProfile(22L));
        assertEquals(memberBRevision, revision(jdbc, 22L));
        assertEquals(2L, jdbc.queryForObject("SELECT COUNT(*) FROM contents WHERE id=501", Long.class));
        assertEquals(1L, jdbc.queryForObject("SELECT COUNT(*) FROM webtoon_metadata WHERE content_id=501", Long.class));
        assertEquals(1L, jdbc.queryForObject("SELECT COUNT(*) FROM content_external_ids WHERE content_id=501", Long.class));
    }

    private static void verifyConcurrentUpdates(TasteProfileService service, JdbcTemplate jdbc,
                                                TransactionTemplate transactions) throws Exception {
        var surveySaved = new CountDownLatch(1);
        var commitSurvey = new CountDownLatch(1);
        var feedbackStarted = new CountDownLatch(1);
        try (var workers = Executors.newFixedThreadPool(2)) {
            var survey = workers.submit(() -> transactions.executeWithoutResult(status -> {
                service.saveSurvey(33L, Map.of("genres", "fantasy"));
                surveySaved.countDown();
                await(commitSurvey);
            }));
            try {
                await(surveySaved);
                var feedback = workers.submit(() -> transactions.executeWithoutResult(status -> {
                    assertEquals(1, jdbc.queryForObject("SELECT 1", Integer.class));
                    feedbackStarted.countDown();
                    service.saveFeedback(33L, "webtoon", 501L, -1);
                }));
                await(feedbackStarted);
                assertThrows(TimeoutException.class, () -> feedback.get(250, TimeUnit.MILLISECONDS));
                commitSurvey.countDown();
                survey.get(12, TimeUnit.SECONDS);
                feedback.get(12, TimeUnit.SECONDS);
            } finally {
                commitSurvey.countDown();
            }
        }

        var profile = JSON.valueToTree(service.getProfile(33L));
        assertEquals(JSON.readTree("[\"fantasy\"]"), profile.at("/survey/genres"));
        assertEquals(JSON.readTree("{\"fantasy\":-0.5,\"mystery\":-1.0}"),
                profile.at("/profile/dimensions/genres"));
        assertEquals(-1, rating(jdbc, 33L, 501L));
        assertEquals(2, revision(jdbc, 33L));
    }

    private static int rating(JdbcTemplate jdbc, long member, long content) {
        return jdbc.queryForObject("""
                SELECT rating FROM member_content_feedback
                WHERE member_id=? AND content_id=? AND content_type='webtoon'
                """, Integer.class, member, content);
    }

    private static int revision(JdbcTemplate jdbc, long member) {
        return jdbc.queryForObject("SELECT revision FROM member_taste_profiles WHERE member_id=?", Integer.class, member);
    }

    private static void await(CountDownLatch latch) {
        try {
            assertTrue(latch.await(12, TimeUnit.SECONDS), "Timed out waiting for the other transaction");
        } catch (InterruptedException e) {
            Thread.currentThread().interrupt();
            throw new AssertionError("Interrupted while waiting for the other transaction", e);
        }
    }

    @Configuration(proxyBeanMethods = false)
    @EnableTransactionManagement
    static class TransactionConfig {
    }
}
