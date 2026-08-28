package com.smartcustomerservice.business.aftersales.payment;

import java.math.BigDecimal;

/** 支付退款端口，afterSalesNo是支付侧幂等业务号。 */
public interface PaymentRefundGateway {
    PaymentRefundResult refund(String afterSalesNo, BigDecimal amount);
}
