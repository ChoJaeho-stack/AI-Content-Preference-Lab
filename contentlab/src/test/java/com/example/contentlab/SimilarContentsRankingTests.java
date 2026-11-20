package com.example.contentlab;

import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.entity.Content;
import com.example.contentlab.entity.ContentId;
import com.example.contentlab.repository.ContentRepository;
import com.example.contentlab.repository.RecommendationHistoryRepository;
import com.example.contentlab.service.AiRecommendationClient;
import com.example.contentlab.service.ContentService;
import org.junit.jupiter.api.Test;
import org.springframework.jdbc.core.JdbcTemplate;

import java.util.List;
import java.util.Optional;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class SimilarContentsRankingTests {
    @Test
    void webtoonSimilarityNeverReturnsMovieOrTvRows() {
        var repository = mock(ContentRepository.class);
        var service = new ContentService(repository, mock(RecommendationHistoryRepository.class),
                mock(JdbcTemplate.class), mock(AiRecommendationClient.class));
        var target = content(1L, "webtoon", "[1]", 8.0, 90.0);
        var webtoon = content(2L, "webtoon", "[1]", 8.0, 90.0);
        var movie = content(3L, "movie", "[1]", 10.0, 100.0);

        when(repository.findById(new ContentId(1L, "webtoon"))).thenReturn(Optional.of(target));
        when(repository.findByExcludedFalse()).thenReturn(List.of(target, movie, webtoon));

        assertEquals(List.of(ContentResponse.from(webtoon)), service.getSimilarContents("webtoon", 1L));
    }

    @Test
    void keepsScoresAndEncounterOrderAtTheTopSixCutoff() {
        var repository = mock(ContentRepository.class);
        var service = new ContentService(repository, mock(RecommendationHistoryRepository.class),
                mock(JdbcTemplate.class), mock(AiRecommendationClient.class));
        var target = content(1L, "movie", "[28,28,35]", 8.0, 90.0);
        var sameIdDifferentType = content(1L, "tv", "[28,35]", 10.0, 100.0);
        var malformed = content(2L, "movie", "not-json", 11.0, 200.0);
        var nullValues = content(3L, "movie", null, null, null);
        var tiedFirst = content(8L, "movie", "[28]", 10.0, 100.0);
        var tiedSecond = content(7L, "movie", "[28]", 10.0, 100.0);
        var tiedThird = content(6L, "movie", "[28]", 10.0, 100.0);
        var tiedFourth = content(5L, "movie", "[28]", 10.0, 100.0);
        var tiedFifth = content(4L, "movie", "[28]", 10.0, 100.0);
        var top = content(9L, "movie", "[35,28]", 10.0, 100.0);

        when(repository.findById(new ContentId(1L, "movie"))).thenReturn(Optional.of(target));
        when(repository.findByExcludedFalse()).thenReturn(List.of(
                nullValues, malformed, tiedFirst, target, tiedSecond, sameIdDifferentType,
                tiedThird, tiedFourth, tiedFifth, top));

        var expected = List.of(top, sameIdDifferentType, tiedFirst, tiedSecond, tiedThird, tiedFourth)
                .stream().map(ContentResponse::from).toList();
        assertEquals(expected, service.getSimilarContents("movie", 1L));
    }

    private static Content content(Long id, String type, String genreIds, Double rating, Double popularity) {
        var item = mock(Content.class);
        when(item.getId()).thenReturn(id);
        when(item.getType()).thenReturn(type);
        when(item.getGenreIds()).thenReturn(genreIds);
        when(item.getRating()).thenReturn(rating);
        when(item.getPopularity()).thenReturn(popularity);
        return item;
    }
}
