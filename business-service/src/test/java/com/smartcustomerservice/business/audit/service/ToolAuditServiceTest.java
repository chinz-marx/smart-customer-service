package com.smartcustomerservice.business.audit.service;

import com.smartcustomerservice.business.audit.config.ToolAuditConfiguration;
import com.smartcustomerservice.business.audit.domain.ToolCallAudit;
import com.smartcustomerservice.business.audit.mapper.ToolCallAuditMapper;
import org.junit.jupiter.api.Test;

import java.util.concurrent.CountDownLatch;
import java.util.concurrent.Executors;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.*;

class ToolAuditServiceTest {
    @Test
    void returnsWhileDatabaseIsBlockedAndDrainsAcceptedWritesOnShutdown() throws Exception {
        var executor = new ToolAuditConfiguration().toolAuditExecutor(1, 1);
        executor.initialize();
        var mapper = mock(ToolCallAuditMapper.class);
        var entered = new CountDownLatch(1);
        var release = new CountDownLatch(1);
        var worker = new AtomicReference<String>();
        var saved = new AtomicReference<ToolCallAudit>();
        when(mapper.insert(any(ToolCallAudit.class))).thenAnswer(call -> {
            worker.set(Thread.currentThread().getName());
            saved.set(call.getArgument(0));
            entered.countDown();
            if (!release.await(5, TimeUnit.SECONDS)) throw new AssertionError("save not released");
            return 1;
        });
        var service = new ToolAuditService(mapper, executor);
        try (var caller = Executors.newSingleThreadExecutor()) {
            try {
                caller.submit(() -> record(service, "request-1")).get(1, TimeUnit.SECONDS);
                assertThat(entered.await(1, TimeUnit.SECONDS)).isTrue();
                assertThat(release.getCount()).isEqualTo(1);
                assertThat(worker.get()).startsWith("tool-audit-");
                assertThat(saved.get().getRequestId()).isEqualTo("request-1");
                assertThat(saved.get().getCreatedAt()).isNotNull();

                record(service, "request-2"); // 唯一队列位置被占满。
                caller.submit(() -> record(service, "request-3")).get(1, TimeUnit.SECONDS);
                verify(mapper, times(1)).insert(any(ToolCallAudit.class));
            } finally {
                release.countDown();
                executor.shutdown();
            }
        }
        verify(mapper, times(2)).insert(any(ToolCallAudit.class));
    }

    @Test
    void failedInsertDoesNotPreventLaterAuditWrites() throws Exception {
        var executor = new ToolAuditConfiguration().toolAuditExecutor(1, 2);
        executor.initialize();
        var mapper = mock(ToolCallAuditMapper.class);
        var saved = new CountDownLatch(1);
        when(mapper.insert(any(ToolCallAudit.class)))
                .thenThrow(new IllegalStateException("database unavailable"))
                .thenAnswer(call -> { saved.countDown(); return 1; });
        var service = new ToolAuditService(mapper, executor);
        try {
            record(service, "failed");
            record(service, "next");
            assertThat(saved.await(2, TimeUnit.SECONDS)).isTrue();
        } finally {
            executor.shutdown();
        }
    }

    private static void record(ToolAuditService service, String requestId) {
        service.record("points_query", requestId, "session", "user", null,
                "POINTS_FOUND", true, 12);
    }
}
