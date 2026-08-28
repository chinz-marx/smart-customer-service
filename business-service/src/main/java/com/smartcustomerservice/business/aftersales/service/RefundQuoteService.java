package com.smartcustomerservice.business.aftersales.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteItemInput;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteItemResult;
import com.smartcustomerservice.business.aftersales.api.dto.RefundQuoteResult;
import com.smartcustomerservice.business.aftersales.domain.OrderRefundItem;
import com.smartcustomerservice.business.aftersales.domain.OrderRefundPricing;
import com.smartcustomerservice.business.aftersales.domain.RefundQuoteSnapshot;
import com.smartcustomerservice.business.aftersales.domain.RefundReasonCode;
import com.smartcustomerservice.business.aftersales.mapper.OrderRefundItemMapper;
import com.smartcustomerservice.business.aftersales.mapper.OrderRefundPricingMapper;
import com.smartcustomerservice.business.aftersales.mapper.RefundQuoteSnapshotMapper;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.order.domain.BusinessOrder;
import com.smartcustomerservice.business.order.domain.OrderStatus;
import com.smartcustomerservice.business.order.mapper.BusinessOrderMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.UUID;
import java.util.regex.Pattern;
import java.util.stream.Collectors;

/**
 * 执行只读退款试算，包括售后资格校验、优惠分摊、积分分摊和运费判断。
 *
 * <p>本服务不会创建售后单。正式退款申请必须由未来独立的写操作Tool完成，并再次
 * 校验订单版本、试算快照和用户确认。</p>
 */
@Service
@RequiredArgsConstructor
public class RefundQuoteService {
    private static final Pattern RESOURCE_ID_PATTERN =
            Pattern.compile("^[A-Z0-9_-]{3,64}$");
    private static final Set<OrderStatus> QUOTABLE_STATUSES = Set.of(
            OrderStatus.PAID,
            OrderStatus.PROCESSING,
            OrderStatus.SHIPPED,
            OrderStatus.DELIVERED);
    private static final BigDecimal ZERO = new BigDecimal("0.00");
    private static final int MAX_ITEM_TYPES = 20;
    private static final long QUOTE_TTL_MINUTES = 10;

    private final BusinessOrderMapper orderMapper;
    private final OrderRefundPricingMapper pricingMapper;
    private final OrderRefundItemMapper itemMapper;
    private final RefundQuoteSnapshotMapper snapshotMapper;
    private final ObjectMapper objectMapper;

    @Transactional
    public RefundQuoteResult quote(
            String userId,
            String orderId,
            List<RefundQuoteItemInput> refundItems,
            String reasonCode,
            Boolean received) {
        return evaluate(userId, orderId, refundItems, reasonCode, received, true);
    }

    /** 使用原报价参数重新读取业务数据并试算，但不创建第二个快照。 */
    @Transactional(readOnly = true)
    public RefundQuoteResult recalculate(RefundQuoteSnapshot snapshot) {
        try {
            List<RefundQuoteItemInput> items = objectMapper.readValue(
                    snapshot.getRefundItemsJson(), new TypeReference<>() {
                    });
            return evaluate(
                    snapshot.getUserId(),
                    snapshot.getOrderNo(),
                    items,
                    snapshot.getReasonCode(),
                    snapshot.getReceived(),
                    false);
        } catch (JsonProcessingException exception) {
            throw new BusinessException(BusinessErrorCode.ORDER_DATA_INVALID);
        }
    }

    private RefundQuoteResult evaluate(
            String userId,
            String orderId,
            List<RefundQuoteItemInput> refundItems,
            String reasonCode,
            Boolean received,
            boolean persistSnapshot) {
        String trustedUserId = requireUserId(userId);
        String normalizedOrderId = requireOrderId(orderId);
        RefundReasonCode reason = parseReason(reasonCode);
        OffsetDateTime calculatedAt = OffsetDateTime.now();

        BusinessOrder order = orderMapper.selectOne(
                Wrappers.<BusinessOrder>lambdaQuery()
                        .eq(BusinessOrder::getOrderNo, normalizedOrderId)
                        .eq(BusinessOrder::getUserId, trustedUserId));
        if (order == null) {
            return rejected(normalizedOrderId, calculatedAt,
                    List.of("没有查询到属于当前账号的订单，请核对订单号。"));
        }

        List<String> rejectionReasons = new ArrayList<>();
        if (!QUOTABLE_STATUSES.contains(order.getStatus())) {
            rejectionReasons.add("订单状态“" + order.getStatus().getDisplayName()
                    + "”暂不支持退款试算。");
        }
        validateReceived(reason, received, rejectionReasons);

        Map<String, Integer> requestedQuantities =
                normalizeRequestedItems(refundItems, rejectionReasons);
        if (requestedQuantities.isEmpty()) {
            rejectionReasons.add("至少需要选择一个退款商品。" );
        }

        OrderRefundPricing pricing = pricingMapper.selectOne(
                Wrappers.<OrderRefundPricing>lambdaQuery()
                        .eq(OrderRefundPricing::getOrderNo, normalizedOrderId));
        if (pricing == null) {
            rejectionReasons.add("订单成交价格快照不存在，暂时无法准确试算。" );
        }

        List<OrderRefundItem> orderItems = requestedQuantities.isEmpty()
                ? List.of()
                : itemMapper.selectList(
                        Wrappers.<OrderRefundItem>query()
                                // 列名是代码内固定值，不接收用户输入；普通QueryWrapper也便于脱离
                                // Spring上下文做单元测试，不依赖MyBatis-Plus的Lambda列缓存。
                                .eq("order_no", normalizedOrderId)
                                .in("sku_id", requestedQuantities.keySet()));
        Map<String, OrderRefundItem> itemBySku = orderItems.stream()
                .collect(Collectors.toMap(OrderRefundItem::getSkuId, item -> item));
        validateItems(
                requestedQuantities, itemBySku, calculatedAt, rejectionReasons);

        if (!rejectionReasons.isEmpty() || pricing == null) {
            return rejected(normalizedOrderId, calculatedAt, rejectionReasons);
        }
        RefundQuoteResult result = calculate(
                normalizedOrderId,
                requestedQuantities,
                itemBySku,
                pricing,
                reason,
                Boolean.TRUE.equals(received),
                calculatedAt);
        return persistSnapshot
                ? persistSnapshot(
                        result,
                        trustedUserId,
                        requestedQuantities,
                        reason,
                        Boolean.TRUE.equals(received))
                : result;
    }

    private RefundQuoteResult persistSnapshot(
            RefundQuoteResult result,
            String userId,
            Map<String, Integer> requestedQuantities,
            RefundReasonCode reason,
            boolean received) {
        String quoteToken = "QT_" + UUID.randomUUID().toString().replace("-", "");
        OffsetDateTime expiresAt = result.getCalculatedAt().plusMinutes(QUOTE_TTL_MINUTES);
        List<RefundQuoteItemInput> normalizedItems = requestedQuantities.entrySet().stream()
                .map(entry -> {
                    RefundQuoteItemInput item = new RefundQuoteItemInput();
                    item.setSkuId(entry.getKey());
                    item.setQuantity(entry.getValue());
                    return item;
                })
                .toList();
        try {
            RefundQuoteSnapshot snapshot = new RefundQuoteSnapshot();
            snapshot.setQuoteToken(quoteToken);
            snapshot.setUserId(userId);
            snapshot.setOrderNo(result.getOrderId());
            snapshot.setReasonCode(reason.name());
            snapshot.setReceived(received);
            snapshot.setRefundItemsJson(objectMapper.writeValueAsString(normalizedItems));
            snapshot.setAvailableMethodsJson(
                    objectMapper.writeValueAsString(result.getAvailableMethods()));
            snapshot.setRefundAmount(result.getRefundAmount());
            snapshot.setGoodsAmount(result.getGoodsAmount());
            snapshot.setDiscountDeduction(result.getDiscountDeduction());
            snapshot.setPointsDeduction(result.getPointsDeduction());
            snapshot.setShippingRefund(result.getShippingRefund());
            snapshot.setStatus("ACTIVE");
            snapshot.setExpiresAt(expiresAt);
            snapshotMapper.insert(snapshot);
        } catch (JsonProcessingException exception) {
            throw new BusinessException(BusinessErrorCode.INTERNAL_ERROR);
        }
        return result.toBuilder()
                .quoteToken(quoteToken)
                .quoteExpiresAt(expiresAt)
                .build();
    }

    private RefundQuoteResult calculate(
            String orderId,
            Map<String, Integer> requestedQuantities,
            Map<String, OrderRefundItem> itemBySku,
            OrderRefundPricing pricing,
            RefundReasonCode reason,
            boolean received,
            OffsetDateTime calculatedAt) {
        BigDecimal totalDiscount = money(pricing.getOrderDiscount())
                .add(money(pricing.getCouponDiscount()));
        BigDecimal goodsAmount = ZERO;
        BigDecimal discountDeduction = ZERO;
        BigDecimal pointsDeduction = ZERO;
        List<RefundQuoteItemResult> breakdown = new ArrayList<>();

        for (Map.Entry<String, Integer> requested : requestedQuantities.entrySet()) {
            OrderRefundItem item = itemBySku.get(requested.getKey());
            BigDecimal lineGoodsAmount = item.getUnitPrice()
                    .multiply(BigDecimal.valueOf(requested.getValue()))
                    .setScale(2, RoundingMode.HALF_UP);
            BigDecimal lineDiscount = allocate(
                    totalDiscount, lineGoodsAmount, pricing.getGoodsAmount());
            BigDecimal linePoints = allocate(
                    pricing.getPointsDiscount(), lineGoodsAmount, pricing.getGoodsAmount());
            BigDecimal lineRefund = lineGoodsAmount
                    .subtract(lineDiscount)
                    .subtract(linePoints)
                    .max(ZERO)
                    .setScale(2, RoundingMode.HALF_UP);

            goodsAmount = goodsAmount.add(lineGoodsAmount);
            discountDeduction = discountDeduction.add(lineDiscount);
            pointsDeduction = pointsDeduction.add(linePoints);
            breakdown.add(RefundQuoteItemResult.builder()
                    .skuId(item.getSkuId())
                    .skuName(item.getSkuName())
                    .quantity(requested.getValue())
                    .goodsAmount(lineGoodsAmount)
                    .discountDeduction(lineDiscount)
                    .pointsDeduction(linePoints)
                    .refundableAmount(lineRefund)
                    .build());
        }

        BigDecimal shippingRefund = reason.isMerchantResponsible()
                ? money(pricing.getShippingFee())
                : ZERO;
        BigDecimal refundAmount = goodsAmount
                .subtract(discountDeduction)
                .subtract(pointsDeduction)
                .add(shippingRefund)
                .max(ZERO)
                .setScale(2, RoundingMode.HALF_UP);
        List<String> methods = availableMethods(reason, received);
        List<String> evidence = requiredEvidence(reason);
        String answer = "退款试算完成：所选商品金额" + goodsAmount + "元，扣除分摊优惠"
                + discountDeduction + "元、积分抵扣" + pointsDeduction + "元，预计退还运费"
                + shippingRefund + "元，预计退款总额" + refundAmount
                + "元。本结果仅为试算，提交申请时会根据订单最新状态重新校验。";

        return RefundQuoteResult.builder()
                .eligible(true)
                .orderId(orderId)
                .refundAmount(refundAmount)
                .goodsAmount(goodsAmount)
                .discountDeduction(discountDeduction)
                .pointsDeduction(pointsDeduction)
                .shippingRefund(shippingRefund)
                .itemBreakdown(List.copyOf(breakdown))
                .availableMethods(methods)
                .rejectionReasons(List.of())
                .requiredEvidence(evidence)
                .calculatedAt(calculatedAt)
                .answer(answer)
                .build();
    }

    private void validateReceived(
            RefundReasonCode reason, Boolean received, List<String> rejectionReasons) {
        if (received == null) {
            rejectionReasons.add("需要确认是否已经收到商品。" );
            return;
        }
        if (reason == RefundReasonCode.NOT_RECEIVED && received) {
            rejectionReasons.add("退款原因为未收到货时，received必须为false。" );
        }
        if (reason != RefundReasonCode.NOT_RECEIVED && !received) {
            rejectionReasons.add("除未收到货外的退款原因，需要先确认已经收到商品。" );
        }
    }

    private Map<String, Integer> normalizeRequestedItems(
            List<RefundQuoteItemInput> refundItems, List<String> rejectionReasons) {
        Map<String, Integer> normalized = new LinkedHashMap<>();
        if (refundItems == null || refundItems.isEmpty()) {
            return normalized;
        }
        if (refundItems.size() > MAX_ITEM_TYPES) {
            rejectionReasons.add("一次最多试算" + MAX_ITEM_TYPES + "种商品。" );
            return normalized;
        }
        for (RefundQuoteItemInput input : refundItems) {
            String skuId = input == null
                    ? ""
                    : StringUtils.trimToEmpty(input.getSkuId()).toUpperCase(Locale.ROOT);
            Integer quantity = input == null ? null : input.getQuantity();
            if (!RESOURCE_ID_PATTERN.matcher(skuId).matches()) {
                rejectionReasons.add("商品SKU ID格式不正确。" );
                continue;
            }
            if (quantity == null || quantity <= 0 || quantity > 100) {
                rejectionReasons.add("商品" + skuId + "的退款数量必须在1到100之间。" );
                continue;
            }
            normalized.merge(skuId, quantity, Integer::sum);
        }
        return normalized;
    }

    private void validateItems(
            Map<String, Integer> requestedQuantities,
            Map<String, OrderRefundItem> itemBySku,
            OffsetDateTime calculatedAt,
            List<String> rejectionReasons) {
        requestedQuantities.forEach((skuId, quantity) -> {
            OrderRefundItem item = itemBySku.get(skuId);
            if (item == null) {
                rejectionReasons.add("订单中没有找到商品" + skuId + "。" );
                return;
            }
            if (!Boolean.TRUE.equals(item.getReturnable())) {
                rejectionReasons.add("商品“" + item.getSkuName() + "”不支持退货退款。" );
            }
            if (item.getAfterSaleDeadline() != null
                    && calculatedAt.isAfter(item.getAfterSaleDeadline())) {
                rejectionReasons.add("商品“" + item.getSkuName() + "”已超过售后期限。" );
            }
            if (quantity > item.getRefundableQuantity()) {
                rejectionReasons.add("商品“" + item.getSkuName() + "”最多还能退"
                        + item.getRefundableQuantity() + "件。" );
            }
        });
    }

    private List<String> availableMethods(RefundReasonCode reason, boolean received) {
        if (!received) {
            return List.of("REFUND_ONLY");
        }
        if (reason.isMerchantResponsible()) {
            return List.of("RETURN_AND_REFUND", "EXCHANGE");
        }
        return List.of("RETURN_AND_REFUND");
    }

    private List<String> requiredEvidence(RefundReasonCode reason) {
        return switch (reason) {
            case QUALITY_ISSUE, DAMAGED -> List.of("商品问题照片", "问题视频（可选）");
            case WRONG_ITEM -> List.of("实收商品与订单信息对比照片");
            case NOT_RECEIVED -> List.of("无需上传，系统将核验物流轨迹");
            case PERSONAL_REASON -> List.of("商品及包装完整照片");
        };
    }

    private RefundQuoteResult rejected(
            String orderId, OffsetDateTime calculatedAt, List<String> reasons) {
        List<String> safeReasons = reasons.isEmpty()
                ? List.of("当前订单暂时无法完成退款试算。")
                : List.copyOf(reasons);
        return RefundQuoteResult.builder()
                .eligible(false)
                .orderId(orderId)
                .refundAmount(ZERO)
                .goodsAmount(ZERO)
                .discountDeduction(ZERO)
                .pointsDeduction(ZERO)
                .shippingRefund(ZERO)
                .itemBreakdown(List.of())
                .availableMethods(List.of())
                .rejectionReasons(safeReasons)
                .requiredEvidence(List.of())
                .calculatedAt(calculatedAt)
                .answer("暂时无法完成退款试算：" + String.join("；", safeReasons))
                .build();
    }

    private RefundReasonCode parseReason(String reasonCode) {
        try {
            return RefundReasonCode.valueOf(
                    StringUtils.trimToEmpty(reasonCode).toUpperCase(Locale.ROOT));
        } catch (IllegalArgumentException exception) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
    }

    /** 订单号统一转成大写，和business_order的数据库约束保持一致。 */
    private String requireOrderId(String value) {
        String normalized = StringUtils.trimToEmpty(value).toUpperCase(Locale.ROOT);
        if (!RESOURCE_ID_PATTERN.matcher(normalized).matches()) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return normalized;
    }

    /** 用户ID来自可信登录态，只校验长度并保留大小写，不能按订单号规则转换。 */
    private String requireUserId(String value) {
        String normalized = StringUtils.trimToEmpty(value);
        if (normalized.isEmpty() || normalized.length() > 64) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return normalized;
    }

    private BigDecimal allocate(
            BigDecimal total, BigDecimal lineAmount, BigDecimal totalGoodsAmount) {
        BigDecimal safeTotal = money(total);
        if (safeTotal.signum() == 0 || totalGoodsAmount == null
                || totalGoodsAmount.signum() <= 0) {
            return ZERO;
        }
        return safeTotal.multiply(lineAmount)
                .divide(totalGoodsAmount, 12, RoundingMode.HALF_UP)
                .setScale(2, RoundingMode.HALF_UP);
    }

    private BigDecimal money(BigDecimal value) {
        return value == null ? ZERO : value.setScale(2, RoundingMode.HALF_UP);
    }
}
