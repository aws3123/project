package com.acme.review.repository.mapper;

import com.acme.review.entity.ReviewResult;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.apache.ibatis.annotations.Mapper;

import java.util.List;
import java.util.Optional;

@Mapper
public interface ReviewResultMapper extends BaseMapper<ReviewResult> {

    default ReviewResult upsert(ReviewResult result) {
        if (result.getId() != null) {
            updateById(result);
            return result;
        }

        if (result.getTaskId() == null || result.getTaskId().isBlank()) {
            insert(result);
            return result;
        }

        List<ReviewResult> existingResults = selectList(
                new LambdaQueryWrapper<ReviewResult>().eq(ReviewResult::getTaskId, result.getTaskId())
        );
        if (existingResults.size() > 1) {
            throw new IllegalStateException("Multiple review results found for taskId=" + result.getTaskId());
        }
        if (existingResults.size() == 1) {
            ReviewResult existing = existingResults.get(0);
            result.setId(existing.getId());
            if (result.getCreatedAt() == null) {
                result.setCreatedAt(existing.getCreatedAt());
            }
            updateById(result);
            return result;
        }

        insert(result);
        return result;
    }

    default Optional<ReviewResult> findByTaskId(String taskId) {
        List<ReviewResult> results = selectList(
                new LambdaQueryWrapper<ReviewResult>().eq(ReviewResult::getTaskId, taskId)
        );
        if (results.size() > 1) {
            throw new IllegalStateException("Multiple review results found for taskId=" + taskId);
        }
        return results.stream().findFirst();
    }
}
