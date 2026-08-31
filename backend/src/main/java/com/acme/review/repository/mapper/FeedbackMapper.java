package com.acme.review.repository.mapper;

import com.acme.review.entity.UserFeedback;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;
import org.apache.ibatis.annotations.Param;
import org.apache.ibatis.annotations.Select;

import java.time.Instant;
import java.util.List;
import java.util.Map;

@Mapper
public interface FeedbackMapper extends BaseMapper<UserFeedback> {

    @Select("SELECT feedback_type, COUNT(*) AS cnt FROM user_feedback " +
            "WHERE created_at >= #{from} AND created_at <= #{to} " +
            "AND (#{source} IS NULL OR source = #{source}) " +
            "GROUP BY feedback_type")
    List<Map<String, Object>> countByType(@Param("from") Instant from,
                                          @Param("to") Instant to,
                                          @Param("source") String source);

    @Select("SELECT DATE(created_at) AS day, feedback_type, COUNT(*) AS cnt FROM user_feedback " +
            "WHERE created_at >= #{from} AND created_at <= #{to} " +
            "AND (#{source} IS NULL OR source = #{source}) " +
            "GROUP BY DATE(created_at), feedback_type " +
            "ORDER BY day ASC")
    List<Map<String, Object>> dailyBreakdown(@Param("from") Instant from,
                                             @Param("to") Instant to,
                                             @Param("source") String source);
}
