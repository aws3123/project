package com.acme.review.repository.mapper;

import com.acme.review.entity.ReviewTask;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.apache.ibatis.annotations.Mapper;

import java.util.Optional;

@Mapper
public interface ReviewTaskMapper extends BaseMapper<ReviewTask> {

    default Optional<ReviewTask> findByTaskId(String taskId) {
        return Optional.ofNullable(selectOne(
                new LambdaQueryWrapper<ReviewTask>().eq(ReviewTask::getTaskId, taskId).last("LIMIT 1")
        ));
    }

    default void saveOrUpdate(ReviewTask task) {
        if (task.getId() != null) {
            updateById(task);
        } else {
            insert(task);
        }
    }
}
