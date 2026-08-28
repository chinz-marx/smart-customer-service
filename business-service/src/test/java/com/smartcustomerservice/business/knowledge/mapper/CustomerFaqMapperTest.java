package com.smartcustomerservice.business.knowledge.mapper;

import org.apache.ibatis.annotations.Select;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Method;

import static org.assertj.core.api.Assertions.assertThat;

class CustomerFaqMapperTest {

    @Test
    void commonQuestionsKeepOnlyOneRepresentativeForTheSameAnswer() throws Exception {
        Method list = CustomerFaqMapper.class.getMethod(
                "selectPublishedQuestions", long.class, long.class);
        Method count = CustomerFaqMapper.class.getMethod("countPublishedQuestions");

        String listSql = String.join("", list.getAnnotation(Select.class).value());
        String countSql = String.join("", count.getAnnotation(Select.class).value());

        assertThat(listSql)
                .contains("DISTINCT ON (c.content_hash)")
                .contains("q.question_no ASC");
        assertThat(countSql).contains("COUNT(DISTINCT c.content_hash)");
    }
}
