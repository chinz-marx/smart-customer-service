package com.smartcustomerservice.business.knowledge.api;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.common.api.ToolResponse;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.common.trace.RequestIdFilter;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqAnswerRequest;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqChatAnswer;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqQuestion;
import com.smartcustomerservice.business.knowledge.api.dto.CustomerFaqStreamDone;
import com.smartcustomerservice.business.knowledge.api.dto.PageResult;
import com.smartcustomerservice.business.knowledge.service.CustomerFaqService;
import com.smartcustomerservice.business.knowledge.service.CustomerFaqChatService;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import lombok.RequiredArgsConstructor;
import lombok.extern.slf4j.Slf4j;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.StreamingResponseBody;

import java.io.IOException;
import java.io.OutputStream;
import java.nio.charset.StandardCharsets;
import java.util.Map;

/** 客服端确定性常见问题接口；运行时不调用Python、Embedding或LLM。 */
@Slf4j
@RestController
@RequestMapping("/api/customer/faqs")
@RequiredArgsConstructor
public class CustomerFaqController {
    private static final int STREAM_CHUNK_CODE_POINTS = 24;

    private final CustomerFaqService service;
    private final CustomerFaqChatService chatService;
    private final ObjectMapper objectMapper;

    @GetMapping
    public ToolResponse<PageResult<CustomerFaqQuestion>> list(
            @RequestParam(defaultValue = "1") long page,
            @RequestParam(defaultValue = "5") long size,
            HttpServletRequest request) {
        return success("CUSTOMER_FAQ_LIST_OK", service.list(page, size), request);
    }

    @PostMapping("/{questionId}/answer")
    public ToolResponse<CustomerFaqChatAnswer> answer(
            @PathVariable long questionId,
            @Valid @RequestBody CustomerFaqAnswerRequest answerRequest,
            HttpServletRequest request) {
        return success("CUSTOMER_FAQ_ANSWER_OK",
                chatService.answer(questionId, answerRequest), request);
    }

    /**
     * Java确定性FAQ流：delta只发送答案片段，done只发送持久化身份，避免问题或答案重复。
     */
    @PostMapping(
            value = "/{questionId}/answer/stream",
            produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public ResponseEntity<StreamingResponseBody> answerStream(
            @PathVariable long questionId,
            @Valid @RequestBody CustomerFaqAnswerRequest answerRequest,
            HttpServletRequest request) {
        String requestId = requestId(request);
        StreamingResponseBody stream = output -> {
            try {
                CustomerFaqChatAnswer answer = chatService.answer(questionId, answerRequest);
                writeAnswerDeltas(output, answer.answer());
                writeEvent(output, "done", new CustomerFaqStreamDone(
                        answer.questionId(), answer.source(), answer.sessionId(),
                        answer.conversationId(), answer.userMessageId(),
                        answer.assistantMessageId(), answer.createdAt()));
            } catch (Exception exception) {
                String message = exception instanceof BusinessException
                        ? exception.getMessage()
                        : "业务服务暂时不可用";
                log.error("FAQ流式回答失败: questionId={}, requestId={}",
                        questionId, requestId, exception);
                writeEvent(output, "error", Map.of(
                        "message", message,
                        "requestId", requestId));
            }
        };
        return ResponseEntity.ok()
                .contentType(MediaType.TEXT_EVENT_STREAM)
                .header("Cache-Control", "no-cache")
                .header("X-Accel-Buffering", "no")
                .body(stream);
    }

    private void writeAnswerDeltas(OutputStream output, String answer) throws IOException {
        int offset = 0;
        while (offset < answer.length()) {
            int remainingCodePoints = answer.codePointCount(offset, answer.length());
            int chunkCodePoints = Math.min(STREAM_CHUNK_CODE_POINTS, remainingCodePoints);
            int end = answer.offsetByCodePoints(offset, chunkCodePoints);
            writeEvent(output, "delta", Map.of("content", answer.substring(offset, end)));
            offset = end;
        }
    }

    private void writeEvent(OutputStream output, String event, Object data) throws IOException {
        String payload = "event: " + event + "\n"
                + "data: " + objectMapper.writeValueAsString(data) + "\n\n";
        output.write(payload.getBytes(StandardCharsets.UTF_8));
        output.flush();
    }

    private <T> ToolResponse<T> success(String code, T data, HttpServletRequest request) {
        String requestId = requestId(request);
        return ToolResponse.success(code, "操作成功",
                requestId, data);
    }

    private String requestId(HttpServletRequest request) {
        Object value = request.getAttribute(RequestIdFilter.ATTRIBUTE_NAME);
        return value == null ? "unknown" : value.toString();
    }
}
