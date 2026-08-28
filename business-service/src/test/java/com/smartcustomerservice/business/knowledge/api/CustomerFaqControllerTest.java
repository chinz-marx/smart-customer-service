package com.smartcustomerservice.business.knowledge.api;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.datatype.jsr310.JavaTimeModule;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswerRequest;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqChatAnswer;
import com.smartcustomerservice.business.knowledge.service.CustomerFaqChatService;
import com.smartcustomerservice.business.knowledge.service.CustomerFaqService;
import org.junit.jupiter.api.Test;
import org.springframework.http.ResponseEntity;
import org.springframework.mock.web.MockHttpServletRequest;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.when;

class CustomerFaqControllerTest {

    @Test
    void streamSendsAnswerDeltasAndDoesNotRepeatQuestionOrFullAnswerInDone() throws Exception {
        CustomerFaqService faqService = mock(CustomerFaqService.class);
        CustomerFaqChatService chatService = mock(CustomerFaqChatService.class);
        ObjectMapper objectMapper = new ObjectMapper().registerModule(new JavaTimeModule());
        CustomerFaqController controller = new CustomerFaqController(
                faqService, chatService, objectMapper);
        CustomerFaqAnswerRequest request = new CustomerFaqAnswerRequest(null, null);
        String question = "积分怎么保持有效？";
        String answer = "这是一段足够长的确定性答案，用于验证服务端会拆成多个片段流式输出，"
                + "并且完成事件不会再次携带完整答案。";
        when(chatService.answer(12, request)).thenReturn(new CustomerFaqChatAnswer(
                12L, question, answer, "redis", "session-1", "conversation-1",
                "user-message-1", "assistant-message-1", OffsetDateTime.parse("2026-08-28T00:00:00Z")));
        MockHttpServletRequest servletRequest = new MockHttpServletRequest();
        servletRequest.setAttribute(RequestIdFilter.ATTRIBUTE_NAME, "request-1");

        ResponseEntity<StreamingResponseBody> response = controller.answerStream(
                12, request, servletRequest);
        ByteArrayOutputStream output = new ByteArrayOutputStream();
        response.getBody().writeTo(output);
        String body = output.toString(StandardCharsets.UTF_8);

        assertThat(body).doesNotContain(question);
        assertThat(body.split("event: delta", -1).length - 1).isGreaterThan(1);

        StringBuilder reconstructed = new StringBuilder();
        JsonNode done = null;
        for (String block : body.split("\\n\\n")) {
            String[] lines = block.split("\\n", 2);
            if (lines.length != 2 || !lines[1].startsWith("data: ")) {
                continue;
            }
            JsonNode data = objectMapper.readTree(lines[1].substring(6));
            if ("event: delta".equals(lines[0])) {
                reconstructed.append(data.path("content").asText());
            } else if ("event: done".equals(lines[0])) {
                done = data;
            }
        }
        assertThat(reconstructed.toString()).isEqualTo(answer);
        assertThat(done).isNotNull();
        assertThat(done.has("answer")).isFalse();
        assertThat(done.has("questionText")).isFalse();
        assertThat(done.path("assistantMessageId").asText()).isEqualTo("assistant-message-1");
    }
}
