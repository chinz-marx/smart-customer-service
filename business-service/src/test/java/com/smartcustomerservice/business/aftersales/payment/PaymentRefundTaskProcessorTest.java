package com.smartcustomerservice.business.aftersales.payment;

import com.smartcustomerservice.business.aftersales.domain.PaymentRefundTask;
import com.smartcustomerservice.business.aftersales.mapper.AfterSalesOrderMapper;
import com.smartcustomerservice.business.aftersales.mapper.PaymentRefundTaskMapper;
import com.smartcustomerservice.business.customer.mapper.CustomerRefundRecordMapper;
import org.junit.jupiter.api.Test;

import java.math.BigDecimal;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.isNull;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.times;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

/** 异步假支付成功后的状态回写测试。 */
class PaymentRefundTaskProcessorTest {

    @Test
    void shouldUpdateTaskApplicationAndRefundProgressAfterPayment() {
        PaymentRefundTaskMapper taskMapper = mock(PaymentRefundTaskMapper.class);
        AfterSalesOrderMapper afterSalesMapper = mock(AfterSalesOrderMapper.class);
        CustomerRefundRecordMapper refundRecordMapper =
                mock(CustomerRefundRecordMapper.class);
        PaymentRefundGateway gateway = mock(PaymentRefundGateway.class);
        PaymentRefundTask task = new PaymentRefundTask();
        task.setId(1L);
        task.setAfterSalesNo("AS_TEST");
        task.setRefundAmount(new BigDecimal("91.55"));
        task.setStatus("PENDING");
        task.setAttempts(0);

        when(taskMapper.selectById(1L)).thenReturn(task);
        when(taskMapper.update(isNull(), any())).thenReturn(1);
        when(gateway.refund("AS_TEST", new BigDecimal("91.55")))
                .thenReturn(new PaymentRefundResult(true, "MOCK_PAY_TEST", null));
        PaymentRefundTaskProcessor processor = new PaymentRefundTaskProcessor(
                taskMapper, afterSalesMapper, refundRecordMapper, gateway);

        processor.process(1L);

        verify(gateway).refund("AS_TEST", new BigDecimal("91.55"));
        verify(taskMapper, times(2)).update(isNull(), any());
        verify(afterSalesMapper).update(isNull(), any());
        verify(refundRecordMapper).update(isNull(), any());
    }
}
