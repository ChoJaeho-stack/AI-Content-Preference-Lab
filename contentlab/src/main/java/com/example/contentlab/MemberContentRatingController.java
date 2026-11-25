package com.example.contentlab;

import com.example.contentlab.service.MemberContentRatingService;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

@RestController
public class MemberContentRatingController {
    private final MemberContentRatingService ratings;

    public MemberContentRatingController(MemberContentRatingService ratings) {
        this.ratings = ratings;
    }

    @GetMapping("/api/me/ratings/{type}/{id}")
    public RatingResponse get(@PathVariable("type") String type, @PathVariable("id") long id,
            JwtAuthenticationToken authentication) {
        return new RatingResponse(ratings.get(memberId(authentication), type, id));
    }

    @PutMapping("/api/me/ratings")
    public RatingResponse save(@RequestBody RatingRequest request,
            JwtAuthenticationToken authentication) {
        return new RatingResponse(ratings.save(memberId(authentication), request.type(), request.id(),
                request.rating()));
    }

    private static long memberId(JwtAuthenticationToken authentication) {
        Number id = authentication.getToken().getClaim("memberId");
        return id.longValue();
    }

    public record RatingRequest(String type, long id, int rating) {}
    public record RatingResponse(Integer rating) {}
}
