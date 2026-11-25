package com.example.contentlab;

import com.example.contentlab.service.TasteProfileService;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

@RestController
public class TasteProfileController {
    private final TasteProfileService service;

    public TasteProfileController(TasteProfileService service) {
        this.service = service;
    }

    @GetMapping("/api/me/taste")
    public Map<String, Object> getTaste(JwtAuthenticationToken auth) {
        return service.getProfile(memberId(auth));
    }

    @PutMapping("/api/me/taste/survey")
    public Map<String, Object> saveSurvey(@RequestBody Map<String, Object> survey,
            JwtAuthenticationToken auth) {
        return service.saveSurvey(memberId(auth), survey);
    }

    @PutMapping("/api/me/taste/evaluations")
    public Map<String, Object> saveFeedback(@RequestBody FeedbackRequest feedback,
            JwtAuthenticationToken auth) {
        return service.saveFeedback(memberId(auth), feedback.type(), feedback.id(), feedback.rating());
    }

    @GetMapping("/api/me/taste/evaluations/{type}/{id}")
    public FeedbackResponse getFeedback(@PathVariable("type") String type, @PathVariable("id") long id,
            JwtAuthenticationToken auth) {
        return new FeedbackResponse(service.getFeedback(memberId(auth), type, id));
    }

    @DeleteMapping("/api/me/taste/evaluations/{type}/{id}")
    public Map<String, Object> deleteFeedback(@PathVariable String type, @PathVariable long id,
            JwtAuthenticationToken auth) {
        return service.deleteFeedback(memberId(auth), type, id);
    }

    private static long memberId(JwtAuthenticationToken auth) {
        Number claim = auth.getToken().getClaim("memberId");
        return claim.longValue();
    }

    public record FeedbackRequest(String type, long id, int rating) {}

    public record FeedbackResponse(Integer rating) {}
}
