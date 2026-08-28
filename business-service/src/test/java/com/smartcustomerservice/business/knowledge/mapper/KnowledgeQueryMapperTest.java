package com.smartcustomerservice.business.knowledge.mapper;

import org.apache.ibatis.annotations.Select;
import org.apache.ibatis.mapping.BoundSql;
import org.apache.ibatis.mapping.SqlSource;
import org.apache.ibatis.scripting.xmltags.XMLLanguageDriver;
import org.apache.ibatis.session.Configuration;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;
import java.util.HashMap;
import java.util.Map;

import static org.assertj.core.api.Assertions.assertThat;

class KnowledgeQueryMapperTest {

    @Test
    void publishedAndPendingViewsJoinTheirOwnVersion() throws Exception {
        Method method = KnowledgeQueryMapper.class.getMethod(
                "selectPage", String.class, Long.class, String.class, long.class, long.class);
        String script = String.join("", method.getAnnotation(Select.class).value());
        XMLLanguageDriver driver = new XMLLanguageDriver();
        SqlSource source = driver.createSqlSource(new Configuration(), script, Map.class);

        assertThat(normalizedSql(source, "published"))
                .contains("ON v.id = k.current_version_id")
                .doesNotContain("ON v.id = k.pending_version_id");
        assertThat(normalizedSql(source, "pending"))
                .contains("ON v.id = k.pending_version_id")
                .doesNotContain("ON v.id = k.current_version_id");
    }

    private String normalizedSql(SqlSource source, String view) {
        Map<String, Object> parameters = new HashMap<>();
        parameters.put("keyword", null);
        parameters.put("categoryId", null);
        parameters.put("view", view);
        parameters.put("limit", 15L);
        parameters.put("offset", 0L);
        BoundSql boundSql = source.getBoundSql(parameters);
        return boundSql.getSql().replaceAll("\\s+", " ").trim();
    }
}
