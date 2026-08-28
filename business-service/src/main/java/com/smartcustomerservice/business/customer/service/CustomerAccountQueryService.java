package com.smartcustomerservice.business.customer.service;

import com.baomidou.mybatisplus.core.toolkit.Wrappers;
import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import com.smartcustomerservice.business.customer.api.dto.BenefitsToolResult;
import com.smartcustomerservice.business.customer.api.dto.PointsToolResult;
import com.smartcustomerservice.business.customer.api.dto.RefundToolResult;
import com.smartcustomerservice.business.customer.api.dto.RewardToolResult;
import com.smartcustomerservice.business.customer.domain.CustomerMemberProfile;
import com.smartcustomerservice.business.customer.domain.CustomerPointsAccount;
import com.smartcustomerservice.business.customer.domain.CustomerRefundRecord;
import com.smartcustomerservice.business.customer.domain.CustomerRewardRecord;
import com.smartcustomerservice.business.customer.mapper.CustomerMemberProfileMapper;
import com.smartcustomerservice.business.customer.mapper.CustomerPointsAccountMapper;
import com.smartcustomerservice.business.customer.mapper.CustomerRefundRecordMapper;
import com.smartcustomerservice.business.customer.mapper.CustomerRewardRecordMapper;
import lombok.RequiredArgsConstructor;
import org.apache.commons.lang3.StringUtils;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.OffsetDateTime;
import java.time.format.DateTimeFormatter;
import java.util.Locale;
import java.util.regex.Pattern;

/**
 * 查询用户积分、奖励、会员权益和退款进度。
 *
 * <p>所有查询都把可信登录用户ID放入SQL条件，不能先查询业务记录再在Java中判断归属，
 * 否则不同提示可能泄露其他用户的数据是否存在。</p>
 */
@Service
@RequiredArgsConstructor
public class CustomerAccountQueryService {
    private static final Pattern RESOURCE_ID_PATTERN = Pattern.compile("^[A-Z0-9_-]{6,64}$");
    private static final DateTimeFormatter DATE_TIME_FORMATTER =
            DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm");

    private final CustomerPointsAccountMapper pointsMapper;
    private final CustomerRewardRecordMapper rewardMapper;
    private final CustomerMemberProfileMapper memberMapper;
    private final CustomerRefundRecordMapper refundMapper;

    @Transactional(readOnly = true)
    public PointsToolResult queryPoints(String userId) {
        String trustedUserId = requireUserId(userId);
        CustomerPointsAccount account = pointsMapper.selectOne(
                Wrappers.<CustomerPointsAccount>lambdaQuery()
                        .eq(CustomerPointsAccount::getUserId, trustedUserId));
        if (account == null) {
            return PointsToolResult.builder()
                    .found(false)
                    .answer("暂未查询到您的积分账户，请联系人工客服核查账户状态。")
                    .build();
        }

        String expiry = account.getExpireDate() == null
                ? "暂无即将到期积分"
                : account.getExpireDate().toString();
        return PointsToolResult.builder()
                .found(true)
                .pointsBalance(account.getPointsBalance())
                .expiringPoints(account.getExpiringPoints())
                .expireDate(account.getExpireDate())
                .updatedAt(account.getUpdatedAt())
                .answer("您好，您当前共有" + account.getPointsBalance() + "积分，其中"
                        + account.getExpiringPoints() + "积分即将到期，到期时间：" + expiry
                        + "。积分变动以业务系统最新记录为准。")
                .build();
    }

    @Transactional(readOnly = true)
    public RewardToolResult queryReward(String userId, String activityName) {
        String trustedUserId = requireUserId(userId);
        String normalizedActivity = StringUtils.trimToNull(activityName);
        CustomerRewardRecord reward = rewardMapper.selectOne(
                Wrappers.<CustomerRewardRecord>lambdaQuery()
                        .eq(CustomerRewardRecord::getUserId, trustedUserId)
                        .like(normalizedActivity != null,
                                CustomerRewardRecord::getActivityName, normalizedActivity)
                        .orderByDesc(CustomerRewardRecord::getUpdatedAt)
                        .last("LIMIT 1"));
        if (reward == null) {
            return RewardToolResult.builder()
                    .found(false)
                    .activityName(normalizedActivity)
                    .answer(normalizedActivity == null
                            ? "暂未查询到您的奖励记录，请补充活动名称或联系人工客服核查。"
                            : "暂未查询到“" + normalizedActivity + "”的奖励记录，请核对活动名称。")
                    .build();
        }

        String statusText = rewardStatusText(reward.getStatus());
        String timeText = reward.getIssuedAt() != null
                ? "发放时间：" + format(reward.getIssuedAt())
                : reward.getExpectedAt() != null
                    ? "预计处理时间：" + format(reward.getExpectedAt())
                    : "暂时没有明确的预计时间";
        return RewardToolResult.builder()
                .found(true)
                .rewardNo(reward.getRewardNo())
                .activityName(reward.getActivityName())
                .statusCode(reward.getStatus())
                .statusText(statusText)
                .expectedAt(reward.getExpectedAt())
                .issuedAt(reward.getIssuedAt())
                .updatedAt(reward.getUpdatedAt())
                .answer("您好，您参加的“" + reward.getActivityName() + "”奖励状态为："
                        + statusText + "。" + timeText + "。")
                .build();
    }

    @Transactional(readOnly = true)
    public BenefitsToolResult queryBenefits(String userId) {
        String trustedUserId = requireUserId(userId);
        CustomerMemberProfile profile = memberMapper.selectOne(
                Wrappers.<CustomerMemberProfile>lambdaQuery()
                        .eq(CustomerMemberProfile::getUserId, trustedUserId));
        if (profile == null) {
            return BenefitsToolResult.builder()
                    .found(false)
                    .answer("暂未查询到您的会员权益，请确认账号是否已开通会员。")
                    .build();
        }

        String validText = profile.getValidUntil() == null
                ? "以会员中心展示为准"
                : profile.getValidUntil().toString();
        return BenefitsToolResult.builder()
                .found(true)
                .levelCode(profile.getLevelCode())
                .levelName(profile.getLevelName())
                .growthValue(profile.getGrowthValue())
                .benefitsText(profile.getBenefitsText())
                .validUntil(profile.getValidUntil())
                .updatedAt(profile.getUpdatedAt())
                .answer("您好，您当前是" + profile.getLevelName() + "，成长值为"
                        + profile.getGrowthValue() + "。当前权益：" + profile.getBenefitsText()
                        + "。权益有效期：" + validText + "。")
                .build();
    }

    @Transactional(readOnly = true)
    public RefundToolResult queryRefund(String userId, String orderId) {
        String trustedUserId = requireUserId(userId);
        String normalizedOrderId = StringUtils.trimToEmpty(orderId).toUpperCase(Locale.ROOT);
        if (!RESOURCE_ID_PATTERN.matcher(normalizedOrderId).matches()) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }

        CustomerRefundRecord refund = refundMapper.selectOne(
                Wrappers.<CustomerRefundRecord>lambdaQuery()
                        .eq(CustomerRefundRecord::getUserId, trustedUserId)
                        .eq(CustomerRefundRecord::getOrderNo, normalizedOrderId)
                        .orderByDesc(CustomerRefundRecord::getUpdatedAt)
                        .last("LIMIT 1"));
        if (refund == null) {
            return RefundToolResult.builder()
                    .found(false)
                    .orderId(normalizedOrderId)
                    .answer("没有查询到订单 " + normalizedOrderId
                            + " 的退款记录，请核对订单号或联系人工客服。")
                    .build();
        }

        String statusText = refundStatusText(refund.getStatus());
        String expectedText = refund.getExpectedAt() == null
                ? "到账时间以支付机构处理结果为准"
                : "预计处理时间：" + format(refund.getExpectedAt());
        return RefundToolResult.builder()
                .found(true)
                .refundNo(refund.getRefundNo())
                .orderId(refund.getOrderNo())
                .statusCode(refund.getStatus())
                .statusText(statusText)
                .refundAmount(refund.getRefundAmount())
                .expectedAt(refund.getExpectedAt())
                .updatedAt(refund.getUpdatedAt())
                .answer("您好，订单 " + refund.getOrderNo() + " 的退款状态为："
                        + statusText + "，退款金额：" + refund.getRefundAmount()
                        + "元。" + expectedText + "。")
                .build();
    }

    private String requireUserId(String userId) {
        String value = StringUtils.trimToNull(userId);
        if (value == null || value.length() > 64) {
            throw new BusinessException(BusinessErrorCode.INVALID_ARGUMENT);
        }
        return value;
    }

    private String rewardStatusText(String status) {
        return switch (StringUtils.defaultString(status)) {
            case "PROCESSING" -> "处理中";
            case "ISSUED" -> "已发放";
            case "FAILED" -> "发放失败";
            case "EXPIRED" -> "已失效";
            default -> throw new BusinessException(BusinessErrorCode.INTERNAL_ERROR);
        };
    }

    private String refundStatusText(String status) {
        return switch (StringUtils.defaultString(status)) {
            case "APPLIED" -> "已提交";
            case "PROCESSING" -> "处理中";
            case "APPROVED" -> "审核通过";
            case "REFUNDED" -> "已退款";
            case "REJECTED" -> "审核未通过";
            case "CLOSED" -> "已关闭";
            default -> throw new BusinessException(BusinessErrorCode.INTERNAL_ERROR);
        };
    }

    private String format(OffsetDateTime value) {
        return value.format(DATE_TIME_FORMATTER);
    }
}
