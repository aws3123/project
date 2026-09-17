package com.acme.review.repository.mapper;

import com.acme.review.entity.IncidentRecordDraft;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

import java.util.Optional;

@Mapper
public interface IncidentRecordDraftMapper extends BaseMapper<IncidentRecordDraft> {

    default Optional<IncidentRecordDraft> findByFeedbackId(Long feedbackId) {
        if (feedbackId == null) return Optional.empty();
        return selectList(new LambdaQueryWrapper<IncidentRecordDraft>()
                .eq(IncidentRecordDraft::getFeedbackId, feedbackId)
                .last("LIMIT 1"))
                .stream()
                .findFirst();
    }
}
