package com.smartcustomerservice.business.aftersales.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.aftersales.api.dto.RefundApplyResult;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteResult;
import com.smartcustomerservice.business.aftersales.domain.AfterSalesOrder;
import com.smartcustomerservice.business.aftersales.domain.PaymentRefundTask;
import com.smartcustomerservice.business.aftersales.domain.RefundQuoteSnapshot;
import com.smartcustomerservice.business.aftersales.mapper.AfterSalesOrderMapper;
import com.smartcustomerservice.business.aftersales.mapper.PaymentRefundTaskMapper;
import com.smartcustomerservice.business.aftersales.mapper.RefundQuoteSnapshotMapper;
import com.smartcustomerservice.business.common.lock.RedisDistributedLockService;
import com.smartcustomerservice.business.customer.domain.CustomerRefundRecord;
import com.smartcustomerservice.business.customer.mapper.CustomerRefundRecordMapper;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.transaction.TransactionStatus;
import org.springframework.transaction.support.TransactionCallback;
import org.springframework.transaction.support.TransactionTemplate;

import java.math.BigDecimal;
import java.time.Duration;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.function.Supplier;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyString;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** refund_apply确认、幂等和低风险自动支付分流测试。 */
class RefundApplyServiceTest {
    private RefundQuoteSnapshotMapper snapshotMapper;
    private AfterSalesOrderMapper afterSalesMapper;
    private PaymentRefundTaskMapper paymentTaskMapper;
    private CustomerRefundRecordMapper refundRecordMapper;
    private RefundQuoteService quoteService;
    private RedisDistributedLockService lockService;
    private RefundApplyService service;

    @BeforeEach
    void setUp() {
        snapshotMapper = mock(RefundQuoteSnapshotMapper.class);
        afterSalesMapper = mock(AfterSalesOrderMapper.class);
        paymentTaskMapper = mock(PaymentRefundTaskMapper.class);
        refundRecordMapper = mock(CustomerRefundRecordMapper.class);
        quoteService = mock(RefundQuoteService.class);
        lockService = mock(RedisDistributedLockService.class);
        TransactionTemplate transactionTemplate = mock(TransactionTemplate.class);

        when(lockService.execute(anyString(), any(Duration.class), any()))
                .thenAnswer(invocation -> {
                    Supplier<?> action = invocation.getArgument(2);
                    return action.get();
                });
        when(transactionTemplate.execute(any()))
                .thenAnswer(invocation -> {
                    TransactionCallback<?> callback = invocation.getArgument(0);
                    return callback.doInTransaction(mock(TransactionStatus.class));
                });
        service = new RefundApplyService(
                snapshotMapper,
                afterSalesMapper,
                paymentTaskMapper,
                refundRecordMapper,
                quoteService,
                lockService,
                new ObjectMapper(),
                transactionTemplate);
    }

    @Test
    void shouldRequireExplicitConfirmationWithoutAcquiringLock() {
        RefundApplyResult result = service.apply(
                "demo-user-001", "request-1", validToken(),
                "RETURN_AND_REFUND", false);

        assertThat(result.isCreated()).isFalse();
        assertThat(result.getStatusCode()).isEqualTo("CONFIRMATION_REQUIRED");
        verify(lockService, never()).execute(anyString(), any(Duration.class), any());
        verify(snapshotMapper, never()).insert(any(RefundQuoteSnapshot.class));
    }

    @Test
    void shouldCreateLowRiskApplicationAndPaymentTask() {
        RefundQuoteSnapshot snapshot = activeSnapshot();
        when(snapshotMapper.selectOne(any())).thenReturn(snapshot);
        when(quoteService.recalculate(snapshot)).thenReturn(currentQuote());
        when(refundRecordMapper.selectCount(any())).thenReturn(1L);

        RefundApplyResult result = service.apply(
                "demo-user-001", "request-create-1", snapshot.getQuoteToken(),
                "RETURN_AND_REFUND", true);

        assertThat(result.isCreated()).isTrue();
        assertThat(result.getStatusCode()).isEqualTo("PAYMENT_PROCESSING");
        assertThat(result.isReviewRequired()).isFalse();
        assertThat(result.getPaymentStatus()).isEqualTo("PENDING");
        assertThat(result.getRefundAmount()).isEqualByComparingTo("91.55");
        assertThat(snapshot.getStatus()).isEqualTo("USED");
        verify(afterSalesMapper).insert(any(AfterSalesOrder.class));
        verify(paymentTaskMapper).insert(any(PaymentRefundTask.class));
        verify(refundRecordMapper).insert(any(CustomerRefundRecord.class));
        verify(snapshotMapper).updateById(snapshot);
    }

    @Test
    void shouldReturnExistingApplicationForSameRequestId() {
        AfterSalesOrder existing = new AfterSalesOrder();
        existing.setAfterSalesNo("AS_EXISTING");
        existing.setOrderNo("ORDER_20260809001");
        existing.setStatus("REFUNDED");
        existing.setReviewRequired(false);
        existing.setRefundAmount(new BigDecimal("91.55"));
        when(afterSalesMapper.selectOne(any())).thenReturn(existing);

        RefundApplyResult result = service.apply(
                "demo-user-001", "same-request", validToken(),
                "RETURN_AND_REFUND", true);

        assertThat(result.isCreated()).isFalse();
        assertThat(result.getAfterSalesNo()).isEqualTo("AS_EXISTING");
        assertThat(result.getPaymentStatus()).isEqualTo("SUCCEEDED");
        verify(lockService, never()).execute(anyString(), any(Duration.class), any());
    }

    private RefundQuoteSnapshot activeSnapshot() {
        RefundQuoteSnapshot snapshot = new RefundQuoteSnapshot();
        snapshot.setQuoteToken(validToken());
        snapshot.setUserId("demo-user-001");
        snapshot.setOrderNo("ORDER_20260809001");
        snapshot.setReasonCode("QUALITY_ISSUE");
        snapshot.setReceived(true);
        snapshot.setRefundItemsJson("[{\"skuId\":\"SKU_PHONE_CASE\",\"quantity\":1}]");
        snapshot.setAvailableMethodsJson("[\"RETURN_AND_REFUND\",\"EXCHANGE\"]");
        snapshot.setRefundAmount(new BigDecimal("91.55"));
        snapshot.setStatus("ACTIVE");
        snapshot.setExpiresAt(OffsetDateTime.now().plusMinutes(5));
        return snapshot;
    }

    private RefundQuoteResult currentQuote() {
        return RefundQuoteResult.builder()
                .eligible(true)
                .orderId("ORDER_20260809001")
                .refundAmount(new BigDecimal("91.55"))
                .goodsAmount(new BigDecimal("99.00"))
                .discountDeduction(new BigDecimal("14.96"))
                .pointsDeduction(new BigDecimal("2.49"))
                .shippingRefund(new BigDecimal("10.00"))
                .itemBreakdown(List.of())
                .availableMethods(List.of("RETURN_AND_REFUND", "EXCHANGE"))
                .rejectionReasons(List.of())
                .requiredEvidence(List.of())
                .calculatedAt(OffsetDateTime.now())
                .answer("试算通过")
                .build();
    }

    private String validToken() {
        return "QT_0123456789abcdef0123456789abcdef";
    }
}
