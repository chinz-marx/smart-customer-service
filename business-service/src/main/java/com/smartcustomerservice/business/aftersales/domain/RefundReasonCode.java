package com.smartcustomerservice.business.aftersales.domain;

import lombok.Getter;
import lombok.RequiredArgsConstructor;

/** 退款试算支持的标准原因，避免LLM把任意自然语言直接带入业务规则。 */
@Getter
@RequiredArgsConstructor
public enum RefundReasonCode {
    QUALITY_ISSUE("质量问题", true),
    DAMAGED("商品破损", true),
    WRONG_ITEM("发错商品", true),
    NOT_RECEIVED("未收到货", true),
    PERSONAL_REASON("个人原因不想要", false);

    private final String displayName;
    private final boolean merchantResponsible;
}
