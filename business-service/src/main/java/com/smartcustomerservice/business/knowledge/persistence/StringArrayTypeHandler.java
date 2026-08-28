package com.smartcustomerservice.business.knowledge.persistence;

import org.apache.ibatis.type.BaseTypeHandler;
import org.apache.ibatis.type.JdbcType;

import java.sql.Array;
import java.sql.CallableStatement;
import java.sql.PreparedStatement;
import java.sql.ResultSet;
import java.sql.SQLException;

/** 在 Java String[] 与 PostgreSQL varchar[] 之间做类型安全转换。 */
public class StringArrayTypeHandler extends BaseTypeHandler<String[]> {
    @Override
    public void setNonNullParameter(
            PreparedStatement statement, int index, String[] parameter, JdbcType jdbcType)
            throws SQLException {
        statement.setArray(index, statement.getConnection().createArrayOf("varchar", parameter));
    }

    @Override
    public String[] getNullableResult(ResultSet resultSet, String columnName) throws SQLException {
        return convert(resultSet.getArray(columnName));
    }

    @Override
    public String[] getNullableResult(ResultSet resultSet, int columnIndex) throws SQLException {
        return convert(resultSet.getArray(columnIndex));
    }

    @Override
    public String[] getNullableResult(CallableStatement statement, int columnIndex) throws SQLException {
        return convert(statement.getArray(columnIndex));
    }

    private String[] convert(Array value) throws SQLException {
        return value == null ? new String[0] : (String[]) value.getArray();
    }
}
