package com.smartcustomerservice.business.aftersales.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.aftersales.api.dto.RefundApplyResult;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteResult;
import com.smartcustomerservice.business.aftersales.domain.AfterSalesOrder;
import com.smartcustomerservice.business.aftersales.domain.PaymentRefundTask;
import com.smartcustomerservice.business.aftersales.domain.RefundQuoteSnapshot;
import com.smartcustomerservice.business.aftersales.mapper.AfterSalesOrderMapper;
import com.smartcustomerservice.business.aftersales.mapper.PaymentRefundTaskMapper;
import com.smartcustomerservice.business.aftersales.mapper.RefundQuoteSnapshotMapper;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.common.lock.RedisDistributedLockService;
import com.smartcustomerservice.business.customer.domain.CustomerRefundRecord;
import com.smartcustomerservice.business.customer.mapper.CustomerRefundRecordMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.List;
import java.util.Locale;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;

/**
 * 用户确认后创建正式售后申请。
 *
 * <p>requestId作为幂等键；quoteToken用于恢复快照并获取Redis分布式锁。事务内会
 * 重新试算，金额或商品状态发生变化时拒绝使用旧报价。</p>
 */
@Service
@RequiredArgsConstructor
public class RefundApplyService {
    private static final Pattern QUOTE_TOKEN_PATTERN =
            Pattern.compile("^QT_[A-Fa-f0-9]{32}$");
    private static final Set<String> ALLOWED_METHODS = Set.of(
            "REFUND_ONLY", "RETURN_AND_REFUND", "EXCHANGE");
    private static final BigDecimal MANUAL_REVIEW_AMOUNT = new BigDecimal("500.00");
    private static final long FREQUENT_REFUND_COUNT = 3;

    private final RefundQuoteSnapshotMapper snapshotMapper;
    private final AfterSalesOrderMapper afterSalesMapper;
    private final PaymentRefundTaskMapper paymentTaskMapper;
    private final CustomerRefundRecordMapper refundRecordMapper;
    private final RefundQuoteService quoteService;
    private final RedisDistributedLockService lockService;
    private final ObjectMapper objectMapper;
    private final TransactionTemplate transactionTemplate;

    public RefundApplyResult apply(
            String userId,
            String requestId,
            String quoteToken,
            String method,
            Boolean confirmed) {
        String trustedUserId = requireText(userId, 64);
        String idempotencyKey = requireText(requestId, 64);
        String normalizedToken = StringUtils.trimToEmpty(quoteToken);
        String normalizedMethod = StringUtils.trimToEmpty(method).toUpperCase(Locale.ROOT);

        AfterSalesOrder existing = findByIdempotency(trustedUserId, idempotencyKey);
        if (existing != null) {
            return fromExisting(existing);
        }
        if (!Boolean.TRUE.equals(confirmed)) {
            return notCreated(
                    "CONFIRMATION_REQUIRED",
                    "提交退款申请前，需要您明确确认退款金额、商品和售后方式。");
        }
        if (!QUOTE_TOKEN_PATTERN.matcher(normalizedToken).matches()
                || !ALLOWED_METHODS.contains(normalizedMethod)) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }

        return lockService.execute(
                "refund-apply:" + normalizedToken,
                Duration.ofSeconds(30),
                () -> transactionTemplate.execute(status -> applyLocked(
                                trustedUserId,
                                idempotencyKey,
                                normalizedToken,
                                normalizedMethod)));
    }

    private RefundApplyResult applyLocked(
            String userId,
            String idempotencyKey,
            String quoteToken,
            String method) {
        AfterSalesOrder existing = findByIdempotency(userId, idempotencyKey);
        if (existing != null) {
            return fromExisting(existing);
        }

        RefundQuoteSnapshot snapshot = snapshotMapper.selectOne(
                Wrappers.<RefundQuoteSnapshot>query()
                        .eq("quote_token", quoteToken)
                        .eq("user_id", userId));
        if (snapshot == null) {
            return notCreated("QUOTE_NOT_FOUND", "没有找到有效的退款试算，请重新试算。");
        }
        OffsetDateTime now = OffsetDateTime.now();
        if (!"ACTIVE".equals(snapshot.getStatus()) || now.isAfter(snapshot.getExpiresAt())) {
            expireSnapshot(snapshot, now);
            return notCreated("QUOTE_EXPIRED", "退款试算已失效，请重新试算后再确认。");
        }
        List<String> availableMethods = parseMethods(snapshot.getAvailableMethodsJson());
        if (!availableMethods.contains(method)) {
            return notCreated(
                    "METHOD_NOT_ALLOWED", "当前试算不支持所选售后方式，请重新选择。");
        }

        RefundQuoteResult latest = quoteService.recalculate(snapshot);
        if (!latest.isEligible() || !sameMoney(snapshot.getRefundAmount(), latest.getRefundAmount())) {
            expireSnapshot(snapshot, now);
            return notCreated(
                    "QUOTE_CHANGED", "订单状态或退款金额已经变化，请重新试算后确认。");
        }

        long refundCount = refundRecordMapper.selectCount(
                Wrappers.<CustomerRefundRecord>query().eq("user_id", userId));
        boolean reviewRequired = latest.getRefundAmount().compareTo(MANUAL_REVIEW_AMOUNT) >= 0
                || refundCount >= FREQUENT_REFUND_COUNT;
        String afterSalesNo = newAfterSalesNo();
        String status = reviewRequired ? "PENDING_REVIEW" : "PAYMENT_PROCESSING";

        AfterSalesOrder afterSales = new AfterSalesOrder();
        afterSales.setAfterSalesNo(afterSalesNo);
        afterSales.setQuoteToken(quoteToken);
        afterSales.setIdempotencyKey(idempotencyKey);
        afterSales.setUserId(userId);
        afterSales.setOrderNo(snapshot.getOrderNo());
        afterSales.setMethod(method);
        afterSales.setReasonCode(snapshot.getReasonCode());
        afterSales.setStatus(status);
        afterSales.setRiskLevel(reviewRequired ? "HIGH" : "LOW");
        afterSales.setReviewRequired(reviewRequired);
        afterSales.setRefundAmount(latest.getRefundAmount());
        afterSales.setRefundItemsJson(snapshot.getRefundItemsJson());
        afterSalesMapper.insert(afterSales);

        createRefundProgress(afterSales, now);
        if (!reviewRequired) {
            createPaymentTask(afterSales, now);
        }
        snapshot.setStatus("USED");
        snapshot.setUsedAt(now);
        snapshotMapper.updateById(snapshot);

        String answer = reviewRequired
                ? "退款申请已创建，售后单号" + afterSalesNo
                    + "，退款金额" + latest.getRefundAmount() + "元，当前需要人工审核。"
                : "退款申请已创建，售后单号" + afterSalesNo
                    + "，退款金额" + latest.getRefundAmount()
                    + "元，系统正在异步提交退款，可稍后查询退款进度。";
        return RefundApplyResult.builder()
                .created(true)
                .afterSalesNo(afterSalesNo)
                .orderId(snapshot.getOrderNo())
                .statusCode(status)
                .statusText(reviewRequired ? "等待人工审核" : "退款处理中")
                .reviewRequired(reviewRequired)
                .refundAmount(latest.getRefundAmount())
                .paymentStatus(reviewRequired ? "NOT_STARTED" : "PENDING")
                .answer(answer)
                .build();
    }

    private void createRefundProgress(AfterSalesOrder afterSales, OffsetDateTime now) {
        CustomerRefundRecord record = new CustomerRefundRecord();
        record.setRefundNo(afterSales.getAfterSalesNo());
        record.setOrderNo(afterSales.getOrderNo());
        record.setUserId(afterSales.getUserId());
        record.setStatus(afterSales.getReviewRequired() ? "APPLIED" : "PROCESSING");
        record.setRefundAmount(afterSales.getRefundAmount());
        record.setExpectedAt(now.plusDays(2));
        record.setUpdatedAt(now);
        refundRecordMapper.insert(record);
    }

    private void createPaymentTask(AfterSalesOrder afterSales, OffsetDateTime now) {
        PaymentRefundTask task = new PaymentRefundTask();
        task.setTaskNo("TASK_" + UUID.randomUUID().toString().replace("-", ""));
        task.setAfterSalesNo(afterSales.getAfterSalesNo());
        task.setRefundAmount(afterSales.getRefundAmount());
        task.setStatus("PENDING");
        task.setAttempts(0);
        task.setNextRetryAt(now);
        paymentTaskMapper.insert(task);
    }

    private AfterSalesOrder findByIdempotency(String userId, String idempotencyKey) {
        return afterSalesMapper.selectOne(
                Wrappers.<AfterSalesOrder>query()
                        .eq("user_id", userId)
                        .eq("idempotency_key", idempotencyKey));
    }

    private RefundApplyResult fromExisting(AfterSalesOrder order) {
        return RefundApplyResult.builder()
                .created(false)
                .afterSalesNo(order.getAfterSalesNo())
                .orderId(order.getOrderNo())
                .statusCode(order.getStatus())
                .statusText(statusText(order.getStatus()))
                .reviewRequired(Boolean.TRUE.equals(order.getReviewRequired()))
                .refundAmount(order.getRefundAmount())
                .paymentStatus(paymentStatus(order.getStatus()))
                .answer("该退款申请已经提交，无需重复操作。售后单号："
                        + order.getAfterSalesNo() + "，当前状态：" + statusText(order.getStatus()) + "。")
                .build();
    }

    private RefundApplyResult notCreated(String status, String answer) {
        return RefundApplyResult.builder()
                .created(false)
                .statusCode(status)
                .statusText(answer)
                .reviewRequired(false)
                .refundAmount(BigDecimal.ZERO.setScale(2))
                .paymentStatus("NOT_STARTED")
                .answer(answer)
                .build();
    }

    private void expireSnapshot(RefundQuoteSnapshot snapshot, OffsetDateTime now) {
        if ("ACTIVE".equals(snapshot.getStatus())) {
            snapshot.setStatus("EXPIRED");
            snapshot.setUsedAt(now);
            snapshotMapper.updateById(snapshot);
        }
    }

    private List<String> parseMethods(String json) {
        try {
            return objectMapper.readValue(json, new TypeReference<>() {
            });
        } catch (JsonProcessingException exception) {
            throw new BusinessException(BusinessErrorCode.ORDER_DATA_INVALID);
        }
    }

    private boolean sameMoney(BigDecimal left, BigDecimal right) {
        return left != null && right != null && left.compareTo(right) == 0;
    }

    private String requireText(String value, int maxLength) {
        String normalized = StringUtils.trimToEmpty(value);
        if (normalized.isEmpty() || normalized.length() > maxLength) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return normalized;
    }

    private String newAfterSalesNo() {
        return "AS_" + OffsetDateTime.now().format(DateTimeFormatter.ofPattern("yyyyMMddHHmmss"))
                + "_" + UUID.randomUUID().toString().replace("-", "").substring(0, 8);
    }

    private String statusText(String status) {
        return switch (status) {
            case "PENDING_REVIEW" -> "等待人工审核";
            case "PAYMENT_PROCESSING" -> "退款处理中";
            case "REFUNDED" -> "已退款";
            case "REJECTED" -> "审核未通过";
            case "PAYMENT_FAILED" -> "退款失败";
            default -> "已关闭";
        };
    }

    private String paymentStatus(String status) {
        return switch (status) {
            case "PAYMENT_PROCESSING" -> "PENDING";
            case "REFUNDED" -> "SUCCEEDED";
            case "PAYMENT_FAILED" -> "FAILED";
            default -> "NOT_STARTED";
        };
    }
}
