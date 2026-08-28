package com.smartcustomerservice.business.aftersales.payment;

import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.nio.charset.StandardCharsets;
import java.util.UUID;

/**
 * 本地假支付实现。
 *
 * <p>相同afterSalesNo始终生成相同交易号，模拟真实支付系统的幂等退款。替换为真实
 * 网关时删除@Component并提供新的PaymentRefundGateway实现即可。</p>
 */
@Component
public class MockPaymentRefundGateway implements PaymentRefundGateway {
    @Override
    public PaymentRefundResult refund(String afterSalesNo, BigDecimal amount) {
        if (amount == null || amount.signum() <= 0) {
            return new PaymentRefundResult(false, null, "退款金额必须大于0");
        }
        UUID stableId = UUID.nameUUIDFromBytes(
                afterSalesNo.getBytes(StandardCharsets.UTF_8));
        String transactionNo = "MOCK_PAY_"
                + stableId.toString().replace("-", "").substring(0, 20).toUpperCase();
        return new PaymentRefundResult(true, transactionNo, null);
    }
}
