package com.smartcustomerservice.business.knowledge.service;

import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswer;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswerSource;
import com.smartcustomerservice.business.knowledge.mapper.CustomerFaqMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.data.redis.core.HashOperations;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.ValueOperations;
import org.springframework.test.util.ReflectionTestUtils;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class CustomerFaqServiceTest {
    private CustomerFaqMapper mapper;
    private ValueOperations<String, String> valueOperations;
    private HashOperations<String, Object, Object> hashOperations;
    private CustomerFaqService service;

    @SuppressWarnings("unchecked")
    @BeforeEach
    void setUp() {
        mapper = mock(CustomerFaqMapper.class);
        StringRedisTemplate redisTemplate = mock(StringRedisTemplate.class);
        valueOperations = mock(ValueOperations.class);
        hashOperations = mock(HashOperations.class);
        when(redisTemplate.opsForValue()).thenReturn(valueOperations);
        when(redisTemplate.opsForHash()).thenReturn(hashOperations);
        service = new CustomerFaqService(mapper, redisTemplate);
        ReflectionTestUtils.setField(service, "questionMapPrefix", "cs:knowledge:question-map:");
    }

    @Test
    void answerUsesRedisMappingWithoutQueryingPostgresql() {
        when(valueOperations.get("cs:knowledge:question-map:12")).thenReturn("doc:12");
        when(hashOperations.multiGet(eq("doc:12"), anyList())).thenReturn(
                List.of("积分如何获得？", "完成指定任务可以获得积分。", "approved", "12"));

        CustomerFaqAnswer answer = service.answer(12);

        assertEquals("redis", answer.source());
        assertEquals("完成指定任务可以获得积分。", answer.answer());
        verify(mapper, never()).selectPublishedAnswer(12);
    }

    @Test
    void answerFallsBackToPublishedPostgresqlChunkWhenRedisMisses() {
        when(valueOperations.get("cs:knowledge:question-map:12")).thenReturn(null);
        when(mapper.selectPublishedAnswer(12)).thenReturn(
                new CustomerFaqAnswerSource(12L, "积分如何获得？", "完成指定任务可以获得积分。"));

        CustomerFaqAnswer answer = service.answer(12);

        assertEquals("postgresql", answer.source());
        assertEquals("积分如何获得？", answer.questionText());
    }

    @Test
    void unpublishedQuestionIsNotReturnedAfterCacheMiss() {
        when(valueOperations.get("cs:knowledge:question-map:99")).thenReturn(null);
        when(mapper.selectPublishedAnswer(99)).thenReturn(null);

        assertThrows(BusinessException.class, () -> service.answer(99));
    }
}
