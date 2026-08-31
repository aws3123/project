package com.acme.review.repository;

import com.acme.review.entity.ReviewResult;
import com.acme.review.repository.mapper.ReviewResultMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import java.math.BigDecimal;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@ActiveProfiles("dev")
class ReviewResultRepositoryTest {

    @Autowired
    private ReviewResultMapper reviewResultMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void shouldPersistAndFindByTaskIdWithTextFieldsAndCreatedAt() {
        ReviewResult result = new ReviewResult();
        result.setTaskId("task-result-1");
        result.setRiskScore(BigDecimal.valueOf(0.7));
        result.setRiskSummary("summary");
        result.setNeedHumanReview(true);
        result.setDetails("line1\nline2");
        result.setLogs("log-line");
        result.setErrorCode("WARN");
        result.setErrorMessage("needs review");

        ReviewResult savedResult = reviewResultMapper.upsert(result);

        assertThat(savedResult.getId()).isNotNull();
        assertThat(savedResult.getCreatedAt()).isNotNull();

        ReviewResult loadedResult = reviewResultMapper.findByTaskId("task-result-1").orElseThrow();
        assertThat(loadedResult.getTaskId()).isEqualTo("task-result-1");
        assertThat(loadedResult.getDetails()).isEqualTo("line1\nline2");
        assertThat(loadedResult.getLogs()).isEqualTo("log-line");
        assertThat(loadedResult.isNeedHumanReview()).isTrue();
        assertThat(loadedResult.getCreatedAt()).isNotNull();
    }

    @Test
    void shouldUpdateExistingResultInsteadOfInsertingDuplicateForSameTaskId() {
        ReviewResult first = new ReviewResult();
        first.setTaskId("task-duplicate-1");
        first.setRiskSummary("first");
        first.setErrorCode("ERR");
        ReviewResult savedFirst = reviewResultMapper.upsert(first);

        ReviewResult second = new ReviewResult();
        second.setTaskId("task-duplicate-1");
        second.setRiskSummary("second");
        second.setErrorCode(null);
        ReviewResult savedSecond = reviewResultMapper.upsert(second);

        Integer count = jdbcTemplate.queryForObject(
                "SELECT COUNT(*) FROM review_result WHERE task_id = ?",
                Integer.class,
                "task-duplicate-1"
        );

        ReviewResult loaded = reviewResultMapper.findByTaskId("task-duplicate-1").orElseThrow();
        assertThat(count).isEqualTo(1);
        assertThat(savedSecond.getId()).isEqualTo(savedFirst.getId());
        assertThat(loaded.getRiskSummary()).isEqualTo("second");
        assertThat(loaded.getErrorCode()).isNull();
    }
}
