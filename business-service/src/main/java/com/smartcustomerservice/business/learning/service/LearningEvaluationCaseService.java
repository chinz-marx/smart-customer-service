package com.smartcustomerservice.business.learning.service;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.learning.api.dto.EvaluationCaseListItem;
import com.smartcustomerservice.business.learning.mapper.LearningEvaluationCaseMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

/** 评测中心读取由问题学习流程生成的真实测试用例。 */
@Service
@RequiredArgsConstructor
public class LearningEvaluationCaseService {
    private final LearningEvaluationCaseMapper mapper;

    @Transactional(readOnly = true)
    public PageResult<EvaluationCaseListItem> list(
            String keyword, Integer status, long page, long size) {
        if (status != null && (status < 0 || status > 3)) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        long safePage = Math.max(1, page);
        long safeSize = Math.min(Math.max(1, size), 100);
        String safeKeyword = StringUtils.trimToNull(keyword);
        return new PageResult<>(
                mapper.selectPage(safeKeyword, status, safeSize, (safePage - 1) * safeSize),
                mapper.countPage(safeKeyword, status), safePage, safeSize);
    }
}
