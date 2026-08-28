package com.smartcustomerservice.business.knowledge.service;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswer;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswerRequest;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqChatAnswer;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqConversation;
import com.smartcustomerservice.business.knowledge.mapper.CustomerFaqConversationMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.util.UUID;

/** 将Java确定性FAQ回答写入真实聊天历史，不经过Python聊天链路。 */
@Service
@RequiredArgsConstructor
public class CustomerFaqChatService {
    private final CustomerFaqService faqService;
    private final CustomerFaqConversationMapper conversationMapper;

    @Value("${customer.demo-user-id:demo-user-001}")
    private String userId;

    @Transactional
    public CustomerFaqChatAnswer answer(long questionId, CustomerFaqAnswerRequest request) {
        long started = System.nanoTime();
        CustomerFaqAnswer resolved = faqService.answer(questionId);
        OffsetDateTime now = OffsetDateTime.now(ZoneOffset.UTC);
        CustomerFaqConversation conversation = resolveConversation(request, resolved, now);
        String userMessageId = UUID.randomUUID().toString();
        String assistantMessageId = UUID.randomUUID().toString();
        conversationMapper.insertMessage(
                userMessageId, conversation.id(), "user", resolved.questionText(),
                UUID.randomUUID().toString(), null, null, null, null, now);
        conversationMapper.insertMessage(
                assistantMessageId, conversation.id(), "assistant", resolved.answer(),
                UUID.randomUUID().toString(), "knowledge_query", 1.0,
                "knowledge:direct-" + resolved.source(),
                (double) Duration.ofNanos(System.nanoTime() - started).toMillis(), now);
        conversationMapper.touchConversation(conversation.id(), userId, now);
        return new CustomerFaqChatAnswer(
                resolved.questionId(), resolved.questionText(), resolved.answer(), resolved.source(),
                conversation.sessionId(), conversation.id(), userMessageId, assistantMessageId, now);
    }

    private CustomerFaqConversation resolveConversation(
            CustomerFaqAnswerRequest request,
            CustomerFaqAnswer answer,
            OffsetDateTime now) {
        String conversationId = StringUtils.trimToNull(request.conversationId());
        String sessionId = StringUtils.trimToNull(request.sessionId());
        CustomerFaqConversation conversation = null;
        if (conversationId != null) {
            conversation = conversationMapper.selectById(conversationId, userId);
            if (conversation == null) {
                throw new BusinessException(BusinessErrorCode.RESOURCE_NOT_FOUND);
            }
        } else if (sessionId != null) {
            conversation = conversationMapper.selectBySession(sessionId, userId);
        }
        if (conversation != null) {
            return conversation;
        }

        String createdConversationId = UUID.randomUUID().toString();
        String createdSessionId = sessionId == null ? UUID.randomUUID().toString() : sessionId;
        String title = StringUtils.abbreviate(answer.questionText(), 40);
        conversationMapper.insertConversation(
                createdConversationId, userId, createdSessionId, title, now);
        return new CustomerFaqConversation(createdConversationId, createdSessionId);
    }
}
