package com.example.contentlab;

import com.example.contentlab.dto.WebtoonResponse;
import com.example.contentlab.service.WebtoonCatalogService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
public class WebtoonController {
    private final WebtoonCatalogService catalog;

    public WebtoonController(WebtoonCatalogService catalog) {
        this.catalog = catalog;
    }

    @GetMapping("/api/webtoons")
    public List<WebtoonResponse> search(
            @RequestParam(required = false) String keyword,
            @RequestParam(required = false) String genre,
            @RequestParam(required = false) String status,
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size) {
        return catalog.search(keyword, genre, status, page, size);
    }

    @GetMapping("/api/webtoons/{id}")
    public WebtoonResponse detail(@PathVariable long id) {
        return catalog.get(id);
    }
}
