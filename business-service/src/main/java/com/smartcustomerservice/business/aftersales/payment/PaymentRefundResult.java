package com.smartcustomerservice.business.aftersales.payment;

/** 支付退款网关结果；未来接真实支付系统时保持此业务接口不变。 */
public record PaymentRefundResult(boolean success, String transactionNo, String errorMessage) {
}
