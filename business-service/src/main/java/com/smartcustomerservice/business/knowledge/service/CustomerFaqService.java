package com.smartcustomerservice.business.knowledge.service;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswer;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswerSource;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqQuestion;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.mapper.CustomerFaqMapper;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.util.List;

/** 常见问题走确定性读取：Redis精确映射优先，PostgreSQL当前发布版本兜底。 */
@Slf4j
@Service
@RequiredArgsConstructor
public class CustomerFaqService {
    private static final List<Object> QUESTION_FIELDS = List.of(
            "question", "answer", "status", "question_id");

    private final CustomerFaqMapper mapper;
    private final StringRedisTemplate redisTemplate;

    @Value("${knowledge.faq.question-map-prefix:cs:knowledge:question-map:}")
    private String questionMapPrefix;

    @Transactional(readOnly = true)
    public PageResult<CustomerFaqQuestion> list(long page, long size) {
        long safePage = Math.max(page, 1);
        long safeSize = Math.min(Math.max(size, 1), 20);
        long total = mapper.countPublishedQuestions();
        List<CustomerFaqQuestion> records = mapper.selectPublishedQuestions(
                safeSize, (safePage - 1) * safeSize);
        return new PageResult<>(records, total, safePage, safeSize);
    }

    public CustomerFaqAnswer answer(long questionId) {
        if (questionId <= 0) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        CustomerFaqAnswer redisAnswer = readRedis(questionId);
        if (redisAnswer != null) {
            return redisAnswer;
        }

        CustomerFaqAnswerSource source = mapper.selectPublishedAnswer(questionId);
        if (source == null) {
            throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
        }
        return new CustomerFaqAnswer(
                source.questionId(), source.questionText(), source.chunkContent(), "postgresql");
    }

    private CustomerFaqAnswer readRedis(long questionId) {
        try {
            String redisKey = StringUtils.trimToNull(
                    redisTemplate.opsForValue().get(questionMapPrefix + questionId));
            if (redisKey == null) {
                return null;
            }
            List<Object> values = redisTemplate.opsForHash().multiGet(redisKey, QUESTION_FIELDS);
            if (values == null || values.size() != QUESTION_FIELDS.size()) {
                return null;
            }
            String question = text(values.get(0));
            String answer = text(values.get(1));
            String status = text(values.get(2));
            String mappedQuestionId = text(values.get(3));
            if (question == null || answer == null || !"approved".equals(status)
                    || !Long.toString(questionId).equals(mappedQuestionId)) {
                return null;
            }
            return new CustomerFaqAnswer(questionId, question, answer, "redis");
        } catch (RuntimeException exception) {
            log.warn("常见问题Redis读取失败，降级PostgreSQL: questionId={}, error={}",
                    questionId, exception.getClass().getSimpleName());
            return null;
        }
    }

    private String text(Object value) {
        return StringUtils.trimToNull(value == null ? null : value.toString());
    }
}
