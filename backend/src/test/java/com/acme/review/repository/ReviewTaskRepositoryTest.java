package com.acme.review.repository;

import com.acme.review.entity.ReviewTask;
import com.acme.review.entity.ReviewTaskStatus;
import com.acme.review.repository.mapper.ReviewTaskMapper;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.test.context.ActiveProfiles;

import static org.assertj.core.api.Assertions.assertThat;

@SpringBootTest
@ActiveProfiles("dev")
class ReviewTaskRepositoryTest {

    @Autowired
    private ReviewTaskMapper reviewTaskMapper;

    @Autowired
    private JdbcTemplate jdbcTemplate;

    @Test
    void shouldPersistAndFindByTaskIdWithLowercaseStatusAndAutofilledTimestamps() {
        ReviewTask task = new ReviewTask();
        task.setTaskId("task-123");
        task.setProjectId("proj-1");
        task.setProjectName("proj-name");
        task.setStatus(ReviewTaskStatus.PENDING);

        reviewTaskMapper.saveOrUpdate(task);

        assertThat(task.getId()).isNotNull();
        assertThat(task.getCreatedAt()).isNotNull();
        assertThat(task.getUpdatedAt()).isNotNull();

        ReviewTask loadedTask = reviewTaskMapper.findByTaskId("task-123").orElseThrow();
        assertThat(loadedTask.getStatus()).isEqualTo(ReviewTaskStatus.PENDING);
        assertThat(loadedTask.getCreatedAt()).isNotNull();
        assertThat(loadedTask.getUpdatedAt()).isNotNull();

        String rawStatus = jdbcTemplate.queryForObject(
                "SELECT status FROM review_task WHERE task_id = ?",
                String.class,
                "task-123"
        );
        assertThat(rawStatus).isEqualTo("pending");
    }

    @Test
    void shouldMapLowercaseStatusValuesBackToEnum() {
        assertThat(ReviewTaskStatus.fromDbValue("pending")).isEqualTo(ReviewTaskStatus.PENDING);
        assertThat(ReviewTaskStatus.fromDbValue("processing")).isEqualTo(ReviewTaskStatus.PROCESSING);
        assertThat(ReviewTaskStatus.fromDbValue("success")).isEqualTo(ReviewTaskStatus.SUCCESS);
        assertThat(ReviewTaskStatus.fromDbValue("failed")).isEqualTo(ReviewTaskStatus.FAILED);
        assertThat(ReviewTaskStatus.fromDbValue("human_review")).isEqualTo(ReviewTaskStatus.HUMAN_REVIEW);
    }
}
