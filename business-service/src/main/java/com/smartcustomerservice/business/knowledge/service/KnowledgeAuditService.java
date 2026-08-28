package com.smartcustomerservice.business.knowledge.service;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.knowledge.domain.KnowledgeOperationLog;
import com.smartcustomerservice.business.knowledge.mapper.KnowledgeOperationLogMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;

/** 把对象快照序列化为 JSONB，供问题追踪和审批审计使用。 */
@Service
@RequiredArgsConstructor
public class KnowledgeAuditService {
    private final KnowledgeOperationLogMapper logMapper;
    private final ObjectMapper objectMapper;

    public void record(
            long knowledgeId,
            Long versionId,
            Long approvalId,
            int operationType,
            String operatorId,
            Object before,
            Object after,
            String requestId) {
        KnowledgeOperationLog log = new KnowledgeOperationLog();
        log.setKnowledgeId(knowledgeId);
        log.setVersionId(versionId);
        log.setApprovalId(approvalId);
        log.setOperationType(operationType);
        log.setOperatorId(operatorId);
        log.setBeforeData(toJson(before));
        log.setAfterData(toJson(after));
        log.setRequestId(requestId);
        logMapper.insert(log);
    }

    private String toJson(Object value) {
        if (value == null) {
            return null;
        }
        try {
            return objectMapper.writeValueAsString(value);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("知识操作快照序列化失败", exception);
        }
    }
}
