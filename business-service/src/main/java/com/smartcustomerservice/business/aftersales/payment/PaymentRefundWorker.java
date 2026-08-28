package com.smartcustomerservice.business.aftersales.payment;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.aftersales.domain.PaymentRefundTask;
import com.smartcustomerservice.business.aftersales.mapper.PaymentRefundTaskMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.time.OffsetDateTime;
import java.util.List;

/** 定时扫描待处理任务；真正的并发领取由Processor中的条件更新保证。 */
@Component
@RequiredArgsConstructor
public class PaymentRefundWorker {
    private final PaymentRefundTaskMapper taskMapper;
    private final PaymentRefundTaskProcessor processor;

    @Scheduled(fixedDelayString = "${refund.payment.worker-delay-ms:2000}")
    public void processPendingTasks() {
        List<PaymentRefundTask> tasks = taskMapper.selectList(
                Wrappers.<PaymentRefundTask>query()
                        .in("status", "PENDING", "FAILED")
                        .le("next_retry_at", OffsetDateTime.now())
                        .lt("attempts", 3)
                        .orderByAsc("id")
                        .last("LIMIT 20"));
        for (PaymentRefundTask task : tasks) {
            processor.process(task.getId());
        }
    }
}
