package com.acme.review.repository.mapper;

import com.acme.review.entity.ReviewTaskPayload;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

import java.util.Optional;

@Mapper
public interface ReviewTaskPayloadMapper extends BaseMapper<ReviewTaskPayload> {

    default Optional<ReviewTaskPayload> findByTaskId(String taskId) {
        return Optional.ofNullable(selectById(taskId));
    }
}
