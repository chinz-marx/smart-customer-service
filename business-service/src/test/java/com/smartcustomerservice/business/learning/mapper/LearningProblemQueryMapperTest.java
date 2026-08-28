package com.smartcustomerservice.business.learning.mapper;

import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class LearningProblemQueryMapperTest {

    @Test
    void selectPageKeepsWhitespaceBetweenSelectAndFirstColumn() throws Exception {
        Method method = LearningProblemQueryMapper.class.getMethod(
                "selectPage", String.class, Integer.class, Integer.class, long.class, long.class);
        String sql = String.join("", method.getAnnotation(Select.class).value());

        assertThat(sql).contains("SELECT p.id").doesNotContain("SELECTp.id");
    }
}
