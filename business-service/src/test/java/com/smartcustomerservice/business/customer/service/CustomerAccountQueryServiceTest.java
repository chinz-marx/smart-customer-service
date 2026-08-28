package com.smartcustomerservice.business.customer.service;

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
import org.junit.jupiter.api.Test;

import java.lang.reflect.Proxy;
import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.OffsetDateTime;

import static org.assertj.core.api.Assertions.assertThat;

/** 四个账户类 Tool 的业务查询测试，不连接真实 PostgreSQL。 */
class CustomerAccountQueryServiceTest {

    @Test
    void shouldReturnPointsBalanceAndExpiry() {
        CustomerPointsAccount account = new CustomerPointsAccount();
        account.setUserId("demo-user-001");
        account.setPointsBalance(1280);
        account.setExpiringPoints(120);
        account.setExpireDate(LocalDate.of(2026, 12, 31));
        account.setUpdatedAt(OffsetDateTime.now());

        PointsToolResult result = service(account, null, null, null)
                .queryPoints("demo-user-001");

        assertThat(result.isFound()).isTrue();
        assertThat(result.getPointsBalance()).isEqualTo(1280);
        assertThat(result.getAnswer()).contains("1280积分", "120积分", "2026-12-31");
    }

    @Test
    void shouldReturnLatestRewardStatus() {
        CustomerRewardRecord reward = new CustomerRewardRecord();
        reward.setRewardNo("REWARD_1");
        reward.setActivityName("消费返现活动");
        reward.setStatus("PROCESSING");
        reward.setExpectedAt(OffsetDateTime.now().plusDays(3));
        reward.setUpdatedAt(OffsetDateTime.now());

        RewardToolResult result = service(null, reward, null, null)
                .queryReward("demo-user-001", "消费返现");

        assertThat(result.isFound()).isTrue();
        assertThat(result.getStatusCode()).isEqualTo("PROCESSING");
        assertThat(result.getAnswer()).contains("消费返现活动", "处理中");
    }

    @Test
    void shouldReturnMemberBenefits() {
        CustomerMemberProfile member = new CustomerMemberProfile();
        member.setLevelCode("GOLD");
        member.setLevelName("黄金会员");
        member.setGrowthValue(3680);
        member.setBenefitsText("每月2张运费券");
        member.setValidUntil(LocalDate.of(2027, 8, 9));
        member.setUpdatedAt(OffsetDateTime.now());

        BenefitsToolResult result = service(null, null, member, null)
                .queryBenefits("demo-user-001");

        assertThat(result.isFound()).isTrue();
        assertThat(result.getLevelCode()).isEqualTo("GOLD");
        assertThat(result.getAnswer()).contains("黄金会员", "每月2张运费券");
    }

    @Test
    void shouldNormalizeOrderNumberAndReturnRefundProgress() {
        CustomerRefundRecord refund = new CustomerRefundRecord();
        refund.setRefundNo("REFUND_1");
        refund.setOrderNo("ORDER_20260809001");
        refund.setStatus("PROCESSING");
        refund.setRefundAmount(new BigDecimal("199.00"));
        refund.setExpectedAt(OffsetDateTime.now().plusDays(2));
        refund.setUpdatedAt(OffsetDateTime.now());

        RefundToolResult result = service(null, null, null, refund)
                .queryRefund("demo-user-001", " order_20260809001 ");

        assertThat(result.isFound()).isTrue();
        assertThat(result.getOrderId()).isEqualTo("ORDER_20260809001");
        assertThat(result.getAnswer()).contains("处理中", "199.00元");
    }

    private CustomerAccountQueryService service(
            CustomerPointsAccount points,
            CustomerRewardRecord reward,
            CustomerMemberProfile member,
            CustomerRefundRecord refund) {
        return new CustomerAccountQueryService(
                mapper(CustomerPointsAccountMapper.class, points),
                mapper(CustomerRewardRecordMapper.class, reward),
                mapper(CustomerMemberProfileMapper.class, member),
                mapper(CustomerRefundRecordMapper.class, refund));
    }

    /** 只实现测试所需的 selectOne，其余 Mapper 调用会立即暴露为测试失败。 */
    @SuppressWarnings("unchecked")
    private <T> T mapper(Class<T> mapperType, Object result) {
        return (T) Proxy.newProxyInstance(
                mapperType.getClassLoader(),
                new Class<?>[]{mapperType},
                (proxy, method, arguments) -> {
                    if ("selectOne".equals(method.getName())) {
                        return result;
                    }
                    throw new UnsupportedOperationException(
                            "本测试没有实现 Mapper 方法: " + method.getName());
                });
    }
}
