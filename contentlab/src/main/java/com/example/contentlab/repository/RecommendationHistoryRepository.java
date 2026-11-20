package com.example.contentlab.repository;

import com.example.contentlab.entity.RecommendationHistory;
import org.springframework.data.jpa.repository.JpaRepository;
import org.springframework.stereotype.Repository;
import java.util.List;

@Repository
public interface RecommendationHistoryRepository
        extends JpaRepository<RecommendationHistory, Long> {

    List<RecommendationHistory> findTop20ByMemberIdOrderByCreatedAtDesc(
            Long memberId);

    @org.springframework.transaction.annotation.Transactional
    long deleteByIdAndMemberId(Long id, Long memberId);
}
