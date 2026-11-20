package com.example.contentlab.entity;

import jakarta.persistence.*;

@Entity
@Table(name = "contents")
@IdClass(ContentId.class)
public class Content {

    @Id
    private Long id;

    @Id
    private String type;

    private String title;

    @Column(columnDefinition = "TEXT")
    private String overview;

    @Column(name = "genre_ids", columnDefinition = "JSON")
    private String genreIds;

    private Double rating;

    private Double popularity;

    @Column(columnDefinition = "JSON")
    private String ott;

    @Column(name = "poster_url")
    private String posterUrl;

    @Column(name = "is_excluded")
    private boolean excluded;

    public Content() {
    }

    public Long getId() {
        return id;
    }

    public String getType() {
        return type;
    }

    public String getTitle() {
        return title;
    }

    public String getOverview() {
        return overview;
    }

    public String getGenreIds() {
        return genreIds;
    }

    public Double getRating() {
        return rating;
    }

    public Double getPopularity() {
        return popularity;
    }

    public String getOtt() {
        return ott;
    }

    public String getPosterUrl() {
        return posterUrl;
    }

    public boolean isExcluded() {
        return excluded;
    }
}