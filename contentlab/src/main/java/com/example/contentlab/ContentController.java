package com.example.contentlab;

import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import com.example.contentlab.dto.ContentResponse;
import com.example.contentlab.entity.RecommendationHistory;
import com.example.contentlab.service.ContentService;
import com.example.contentlab.service.CatalogCache;

import org.springframework.web.bind.annotation.*;
import org.springframework.data.domain.Page;

import java.util.List;
import java.util.Map;

@RestController
public class ContentController {

    private final ContentService contentService;
    private final CatalogCache catalogCache;

    public ContentController(ContentService contentService, CatalogCache catalogCache) {
        this.contentService = contentService;
        this.catalogCache = catalogCache;
    }

    @GetMapping("/api/health")
    public Map<String, String> health() {
        return Map.of(
                "status", "success",
                "service", "AI Content Lab"
        );
    }

    @GetMapping("/api/contents")
    public List<ContentResponse> getContents(
            @RequestParam(required = false) String type) {

        return catalogCache.list(type);
    }

    // 콘텐츠 검색 API
    @GetMapping("/api/contents/search")
    public Page<ContentResponse> searchContents(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String type,
            @RequestParam(required = false) String ott,
            @RequestParam(defaultValue = "popularity") String sort,
            @RequestParam(defaultValue = "0") int page,
            @RequestParam(defaultValue = "20") int size) {

        return contentService.searchContents(
                keyword, type, ott, sort, page, size
        );
    }
    // 콘텐츠 상세 조회 API
@GetMapping("/api/contents/{type}/{id}")
public ContentResponse getContentDetail(
        @PathVariable("type") String type,
        @PathVariable("id") Long id) {
    return catalogCache.detail(type, id);
}

@GetMapping("/api/contents/{type}/{id}/similar")
public List<ContentResponse> getSimilarContents(
        @PathVariable("type") String type,
        @PathVariable("id") Long id) {
    return catalogCache.similar(type, id);
}

    @GetMapping("/api/contents/count")
    public Map<String, Long> getCount() {
        return Map.of("count", contentService.getCount());
    }

    @PostMapping("/api/recommend")
public Map recommend(
        @RequestBody Map<String, String> request,
        JwtAuthenticationToken auth) {

    Number memberId = auth.getToken().getClaim("memberId");

    return contentService.recommend(request, memberId.longValue());
}

@GetMapping("/api/history")
public List<RecommendationHistory> getHistory(
        JwtAuthenticationToken auth) {

    Number memberId = auth.getToken().getClaim("memberId");

    return contentService.getHistory(memberId.longValue());
}
    

    @org.springframework.beans.factory.annotation.Autowired
    private com.example.contentlab.repository.RecommendationHistoryRepository historyDeleteRepository;

    @org.springframework.web.bind.annotation.DeleteMapping("/api/history/{id}")
    public org.springframework.http.ResponseEntity<Void> deleteHistory(
            @org.springframework.web.bind.annotation.PathVariable("id") Long id,
            JwtAuthenticationToken auth) {

        Number memberId = auth.getToken().getClaim("memberId");

        long deleted = historyDeleteRepository
                .deleteByIdAndMemberId(id, memberId.longValue());

        if (deleted == 0) {
            return org.springframework.http.ResponseEntity.notFound().build();
        }

        return org.springframework.http.ResponseEntity.noContent().build();
    }
}
