package com.smartcustomerservice.business.knowledge.sync;

import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.learning.sync.ReleaseEvaluationPayload;
import com.smartcustomerservice.business.learning.sync.ReleaseEvaluationResult;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.time.Duration;

/**
 * 使用JDK 21 HttpClient调用Python内部发布接口。
 *
 * <p>请求体先显式序列化为JSON，避免依赖Spring Boot版本对应的消息转换器。</p>
 */
@Component
public class PythonKnowledgeSyncClient {
    private final HttpClient httpClient;
    private final ObjectMapper objectMapper;
    private final String baseUrl;
    private final String internalToken;
    private final Duration requestTimeout;

    public PythonKnowledgeSyncClient(
            ObjectMapper objectMapper,
            @Value("${knowledge.sync.python-base-url:http://127.0.0.1:8000}") String baseUrl,
            @Value("${tool.security.internal-token}") String internalToken,
            @Value("${knowledge.sync.timeout-seconds:30}") long timeoutSeconds) {
        this.objectMapper = objectMapper;
        this.baseUrl = baseUrl.replaceAll("/+$", "");
        this.internalToken = internalToken;
        this.requestTimeout = Duration.ofSeconds(Math.max(1, timeoutSeconds));
        this.httpClient = HttpClient.newBuilder()
                // Uvicorn只提供HTTP/1.1；禁用h2c升级可避免请求体在升级握手中丢失。
                .version(HttpClient.Version.HTTP_1_1)
                .connectTimeout(Duration.ofSeconds(5))
                .build();
    }

    public KnowledgePublishResult publish(KnowledgePublishPayload payload) {
        HttpResponse<String> response = send("/api/internal/knowledge/publish", payload);
        try {
            return objectMapper.readValue(response.body(), KnowledgePublishResult.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Python知识发布响应不是有效JSON", exception);
        }
    }

    public void delete(KnowledgeDeletePayload payload) {
        send("/api/internal/knowledge/delete", payload);
    }

    /** 调用 Python 的正式发布验收执行器，候选知识不会直接进入线上 approved 索引。 */
    public ReleaseEvaluationResult evaluate(ReleaseEvaluationPayload payload) {
        HttpResponse<String> response = send("/api/internal/evaluation/knowledge", payload);
        try {
            return objectMapper.readValue(response.body(), ReleaseEvaluationResult.class);
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("Python自动验收响应不是有效JSON", exception);
        }
    }

    private HttpResponse<String> send(String path, Object payload) {
        try {
            String json = objectMapper.writeValueAsString(payload);
            HttpRequest request = HttpRequest.newBuilder(URI.create(baseUrl + path))
                    .timeout(requestTimeout)
                    .header("Content-Type", "application/json; charset=UTF-8")
                    .header("Accept", "application/json")
                    .header("X-Internal-Token", internalToken)
                    .POST(HttpRequest.BodyPublishers.ofString(json))
                    .build();
            HttpResponse<String> response = httpClient.send(
                    request, HttpResponse.BodyHandlers.ofString());
            if (response.statusCode() < 200 || response.statusCode() >= 300) {
                throw new IllegalStateException(
                        "Python知识发布失败，HTTP状态=" + response.statusCode()
                                + "，响应=" + abbreviate(response.body()));
            }
            return response;
        } catch (JsonProcessingException exception) {
            throw new IllegalStateException("知识发布请求序列化失败", exception);
        } catch (InterruptedException exception) {
            Thread.currentThread().interrupt();
            throw new IllegalStateException("调用Python知识发布接口被中断", exception);
        } catch (IOException exception) {
            throw new IllegalStateException("无法连接Python知识发布接口", exception);
        }
    }

    private String abbreviate(String value) {
        if (value == null || value.length() <= 500) {
            return value;
        }
        return value.substring(0, 500);
    }
}
