package com.acme.review.repository.mapper;

import com.acme.review.entity.ConsumedMessage;
import com.baomidou.mybatisplus.core.mapper.BaseMapper;
import org.apache.ibatis.annotations.Mapper;

@Mapper
public interface ConsumedMessageMapper extends BaseMapper<ConsumedMessage> {
}
