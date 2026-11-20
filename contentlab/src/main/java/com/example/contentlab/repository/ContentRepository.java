package com.example.contentlab.repository;

import com.example.contentlab.entity.Content;
import com.example.contentlab.entity.ContentId;

import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.data.jpa.repository.JpaSpecificationExecutor;
import org.springframework.stereotype.Repository;

import java.util.List;

@Repository
public interface ContentRepository extends
        JpaRepository<Content, ContentId>,
        JpaSpecificationExecutor<Content> {

    List<Content> findByExcludedFalse();

    List<Content> findByTypeAndExcludedFalse(String type);

    long countByExcludedFalse();
}