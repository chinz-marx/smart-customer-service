package com.smartcustomerservice.business.aftersales.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteItemInput;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteResult;
import com.smartcustomerservice.business.aftersales.domain.OrderRefundItem;
import com.smartcustomerservice.business.aftersales.domain.OrderRefundPricing;
import com.smartcustomerservice.business.aftersales.mapper.OrderRefundItemMapper;
import com.smartcustomerservice.business.aftersales.mapper.OrderRefundPricingMapper;
import com.smartcustomerservice.business.aftersales.mapper.RefundQuoteSnapshotMapper;
import com.smartcustomerservice.business.order.domain.BusinessOrder;
import com.smartcustomerservice.business.order.domain.OrderStatus;
import com.smartcustomerservice.business.order.mapper.BusinessOrderMapper;
import org.junit.jupiter.api.Test;

import java.lang.reflect.Proxy;
import java.math.BigDecimal;
import java.time.OffsetDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;

/** 退款试算核心金额和拒绝规则测试，不连接真实PostgreSQL。 */
class RefundQuoteServiceTest {

    @Test
    void shouldAllocateDiscountsAndRefundShippingForQualityIssue() {
        RefundQuoteResult result = service(
                order(OrderStatus.DELIVERED), pricing(), List.of(phoneCase(2)))
                .quote(
                        "demo-user-001",
                        "order_20260809001",
                        List.of(itemInput("sku_phone_case", 1)),
                        "QUALITY_ISSUE",
                        true);

        assertThat(result.isEligible()).isTrue();
        assertThat(result.getGoodsAmount()).isEqualByComparingTo("99.00");
        assertThat(result.getDiscountDeduction()).isEqualByComparingTo("14.96");
        assertThat(result.getPointsDeduction()).isEqualByComparingTo("2.49");
        assertThat(result.getShippingRefund()).isEqualByComparingTo("10.00");
        assertThat(result.getRefundAmount()).isEqualByComparingTo("91.55");
        assertThat(result.getAvailableMethods())
                .containsExactly("RETURN_AND_REFUND", "EXCHANGE");
        assertThat(result.getRequiredEvidence()).contains("商品问题照片");
        assertThat(result.getAnswer()).contains("仅为试算", "91.55元");
        assertThat(result.getQuoteToken()).startsWith("QT_");
        assertThat(result.getQuoteExpiresAt()).isAfter(result.getCalculatedAt());
    }

    @Test
    void shouldNotRefundShippingForPersonalReason() {
        RefundQuoteResult result = service(
                order(OrderStatus.DELIVERED), pricing(), List.of(phoneCase(2)))
                .quote(
                        "demo-user-001",
                        "ORDER_20260809001",
                        List.of(itemInput("SKU_PHONE_CASE", 1)),
                        "PERSONAL_REASON",
                        true);

        assertThat(result.isEligible()).isTrue();
        assertThat(result.getShippingRefund()).isEqualByComparingTo("0.00");
        assertThat(result.getRefundAmount()).isEqualByComparingTo("81.55");
        assertThat(result.getAvailableMethods()).containsExactly("RETURN_AND_REFUND");
    }

    @Test
    void shouldRejectQuantityAboveRemainingRefundableQuantity() {
        RefundQuoteResult result = service(
                order(OrderStatus.DELIVERED), pricing(), List.of(phoneCase(1)))
                .quote(
                        "demo-user-001",
                        "ORDER_20260809001",
                        List.of(itemInput("SKU_PHONE_CASE", 2)),
                        "DAMAGED",
                        true);

        assertThat(result.isEligible()).isFalse();
        assertThat(result.getRefundAmount()).isEqualByComparingTo("0.00");
        assertThat(result.getRejectionReasons()).singleElement()
                .asString()
                .contains("最多还能退1件");
    }

    @Test
    void shouldRejectClosedOrderAndContradictoryReceivedFlag() {
        RefundQuoteResult result = service(
                order(OrderStatus.CLOSED), pricing(), List.of(phoneCase(2)))
                .quote(
                        "demo-user-001",
                        "ORDER_20260809001",
                        List.of(itemInput("SKU_PHONE_CASE", 1)),
                        "NOT_RECEIVED",
                        true);

        assertThat(result.isEligible()).isFalse();
        assertThat(result.getRejectionReasons())
                .anyMatch(reason -> reason.contains("暂不支持退款试算"))
                .anyMatch(reason -> reason.contains("received必须为false"));
    }

    private RefundQuoteService service(
            BusinessOrder order,
            OrderRefundPricing pricing,
            List<OrderRefundItem> items) {
        return new RefundQuoteService(
                mapper(BusinessOrderMapper.class, order, null),
                mapper(OrderRefundPricingMapper.class, pricing, null),
                mapper(OrderRefundItemMapper.class, null, items),
                mapper(RefundQuoteSnapshotMapper.class, null, null),
                new ObjectMapper());
    }

    private BusinessOrder order(OrderStatus status) {
        return BusinessOrder.builder()
                .orderNo("ORDER_20260809001")
                .userId("demo-user-001")
                .status(status)
                .build();
    }

    private OrderRefundPricing pricing() {
        OrderRefundPricing pricing = new OrderRefundPricing();
        pricing.setOrderNo("ORDER_20260809001");
        pricing.setGoodsAmount(new BigDecimal("397.00"));
        pricing.setShippingFee(new BigDecimal("10.00"));
        pricing.setOrderDiscount(new BigDecimal("40.00"));
        pricing.setCouponDiscount(new BigDecimal("20.00"));
        pricing.setPointsDiscount(new BigDecimal("10.00"));
        return pricing;
    }

    private OrderRefundItem phoneCase(int refundableQuantity) {
        OrderRefundItem item = new OrderRefundItem();
        item.setOrderNo("ORDER_20260809001");
        item.setSkuId("SKU_PHONE_CASE");
        item.setSkuName("防摔手机壳");
        item.setUnitPrice(new BigDecimal("99.00"));
        item.setPurchasedQuantity(2);
        item.setRefundableQuantity(refundableQuantity);
        item.setReturnable(true);
        item.setAfterSaleDeadline(OffsetDateTime.now().plusYears(1));
        return item;
    }

    private RefundQuoteItemInput itemInput(String skuId, int quantity) {
        RefundQuoteItemInput input = new RefundQuoteItemInput();
        input.setSkuId(skuId);
        input.setQuantity(quantity);
        return input;
    }

    /** 为BaseMapper测试替身分别实现selectOne和selectList。 */
    @SuppressWarnings("unchecked")
    private <T> T mapper(
            Class<T> mapperType, Object selectedOne, List<?> selectedList) {
        return (T) Proxy.newProxyInstance(
                mapperType.getClassLoader(),
                new Class<?>[]{mapperType},
                (proxy, method, arguments) -> switch (method.getName()) {
                    case "selectOne" -> selectedOne;
                    case "selectList" -> selectedList;
                    case "insert" -> 1;
                    default -> throw new UnsupportedOperationException(
                            "本测试没有实现Mapper方法: " + method.getName());
                });
    }
}
