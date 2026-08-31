package com.acme.review.repository.mapper;

import com.acme.review.entity.TaskAuditLog;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface TaskAuditLogMapper extends BaseMapper<TaskAuditLog> {
}
