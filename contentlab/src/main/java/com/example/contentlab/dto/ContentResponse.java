package com.example.contentlab.dto;

import com.example.contentlab.entity.Content;
import com.fasterxml.jackson.annotation.JsonProperty;

public record ContentResponse(
        Long id,
        String type,
        String title,
        String overview,
        @JsonProperty("genre_ids") String genreIds,
        Double rating,
        Double popularity,
        String ott,
        @JsonProperty("poster_url") String posterUrl
) {

    public static ContentResponse from(Content content) {
        return new ContentResponse(
                content.getId(),
                content.getType(),
                content.getTitle(),
                content.getOverview(),
                content.getGenreIds(),
                content.getRating(),
                content.getPopularity(),
                content.getOtt(),
                content.getPosterUrl()
        );
    }
}