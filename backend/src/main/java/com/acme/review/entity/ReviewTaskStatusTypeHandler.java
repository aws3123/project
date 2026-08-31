package com.acme.review.entity;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

public class ReviewTaskStatusTypeHandler extends BaseTypeHandler<ReviewTaskStatus> {

    @Override
    public void setNonNullParameter(PreparedStatement ps, int i, ReviewTaskStatus parameter, JdbcType jdbcType) throws SQLException {
        ps.setString(i, parameter.getDbValue());
    }

    @Override
    public ReviewTaskStatus getNullableResult(ResultSet rs, String columnName) throws SQLException {
        return ReviewTaskStatus.fromDbValue(rs.getString(columnName));
    }

    @Override
    public ReviewTaskStatus getNullableResult(ResultSet rs, int columnIndex) throws SQLException {
        return ReviewTaskStatus.fromDbValue(rs.getString(columnIndex));
    }

    @Override
    public ReviewTaskStatus getNullableResult(CallableStatement cs, int columnIndex) throws SQLException {
        return ReviewTaskStatus.fromDbValue(cs.getString(columnIndex));
    }
}
