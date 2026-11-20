package com.example.contentlab.dto;

import com.fasterxml.jackson.annotation.JsonProperty;

public record WebtoonResponse(
        Long id,
        String type,
        String title,
        String overview,
        @JsonProperty("genre_ids") String genreIds,
        @JsonProperty("poster_url") String posterUrl,
        String sourceProvider,
        String externalId,
        String servicePlatform,
        String officialUrl,
        String authors,
        String genreTags,
        String storyTags,
        String moodTags,
        String pacing,
        String serialStatus
) {}
