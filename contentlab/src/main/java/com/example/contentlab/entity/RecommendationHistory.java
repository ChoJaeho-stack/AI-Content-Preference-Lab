package com.example.contentlab.entity;

import jakarta.persistence.*;
import java.time.LocalDateTime;

@Entity
@Table(name = "recommendation_history")
public class RecommendationHistory {

    @Id
    @GeneratedValue(strategy = GenerationType.IDENTITY)
    private Long id;

    @Column(name = "member_id")
    private Long memberId;

    @Column(columnDefinition = "TEXT")
    private String liked;

    @Column(columnDefinition = "TEXT")
    private String disliked;

    private String preference;

    @Column(columnDefinition = "JSON", nullable = false)
    private String result;

    @Column(name = "created_at")
    private LocalDateTime createdAt;

    public RecommendationHistory() {}

    public RecommendationHistory(
            Long memberId,
            String liked,
            String disliked,
            String preference,
            String result) {
        this.memberId = memberId;
        this.liked = liked;
        this.disliked = disliked;
        this.preference = preference;
        this.result = result;
        this.createdAt = LocalDateTime.now();
    }

    public Long getId() { return id; }
    public Long getMemberId() { return memberId; }
    public String getLiked() { return liked; }
    public String getDisliked() { return disliked; }
    public String getPreference() { return preference; }
    public String getResult() { return result; }
    public LocalDateTime getCreatedAt() { return createdAt; }
}
