package com.smartcustomerservice.business.aftersales.payment;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.aftersales.domain.AfterSalesOrder;
import com.smartcustomerservice.business.aftersales.domain.PaymentRefundTask;
import com.smartcustomerservice.business.aftersales.mapper.AfterSalesOrderMapper;
import com.smartcustomerservice.business.aftersales.mapper.PaymentRefundTaskMapper;
import com.smartcustomerservice.business.customer.domain.CustomerRefundRecord;
import com.smartcustomerservice.business.customer.mapper.CustomerRefundRecordMapper;
import lombok.RequiredArgsConstructor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;

/** 领取并处理一条退款任务，状态更新在同一个数据库事务中完成。 */
@Service
@RequiredArgsConstructor
public class PaymentRefundTaskProcessor {
    private final PaymentRefundTaskMapper taskMapper;
    private final AfterSalesOrderMapper afterSalesMapper;
    private final CustomerRefundRecordMapper refundRecordMapper;
    private final PaymentRefundGateway paymentGateway;

    @Transactional
    public void process(Long taskId) {
        PaymentRefundTask task = taskMapper.selectById(taskId);
        if (task == null || !("PENDING".equals(task.getStatus())
                || "FAILED".equals(task.getStatus()))) {
            return;
        }

        int claimed = taskMapper.update(
                null,
                Wrappers.<PaymentRefundTask>update()
                        .eq("id", taskId)
                        .in("status", "PENDING", "FAILED")
                        .set("status", "PROCESSING")
                        .set("attempts", task.getAttempts() + 1));
        if (claimed != 1) {
            return;
        }

        PaymentRefundResult result = paymentGateway.refund(
                task.getAfterSalesNo(), task.getRefundAmount());
        OffsetDateTime now = OffsetDateTime.now();
        if (!result.success()) {
            taskMapper.update(
                    null,
                    Wrappers.<PaymentRefundTask>update()
                            .eq("id", taskId)
                            .set("status", "FAILED")
                            .set("last_error", result.errorMessage())
                            .set("next_retry_at", now.plusMinutes(1)));
            if (task.getAttempts() + 1 >= 3) {
                updateAfterSalesStatus(task.getAfterSalesNo(), "PAYMENT_FAILED", null);
            }
            return;
        }

        taskMapper.update(
                null,
                Wrappers.<PaymentRefundTask>update()
                        .eq("id", taskId)
                        .set("status", "SUCCEEDED")
                        .set("payment_transaction_no", result.transactionNo())
                        .set("processed_at", now)
                        .set("last_error", null));
        updateAfterSalesStatus(task.getAfterSalesNo(), "REFUNDED", result.transactionNo());
        updateRefundProgress(task.getAfterSalesNo(), now);
    }

    private void updateAfterSalesStatus(
            String afterSalesNo, String status, String transactionNo) {
        afterSalesMapper.update(
                null,
                Wrappers.<AfterSalesOrder>update()
                        .eq("after_sales_no", afterSalesNo)
                        .set("status", status)
                        .set("payment_transaction_no", transactionNo));
    }

    private void updateRefundProgress(String afterSalesNo, OffsetDateTime now) {
        refundRecordMapper.update(
                null,
                Wrappers.<CustomerRefundRecord>update()
                        .eq("refund_no", afterSalesNo)
                        .set("status", "REFUNDED")
                        .set("expected_at", null)
                        .set("updated_at", now));
    }
}
