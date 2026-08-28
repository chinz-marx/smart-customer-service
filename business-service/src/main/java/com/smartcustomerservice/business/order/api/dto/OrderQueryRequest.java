package com.smartcustomerservice.business.order.api.dto;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Pattern;
import jakarta.validation.constraints.Size;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

/** Python 编排层调用订单查询 Tool 时提交的参数。 */
@Getter
@Setter
@NoArgsConstructor
public class OrderQueryRequest {
    @NotBlank(message = "sessionId 不能为空")
    @Size(max = 64, message = "sessionId 最长 64 个字符")
    private String sessionId;

    /** userId 必须来自登录态或可信上游，不能直接相信用户在聊天中输入的身份。 */
    @NotBlank(message = "userId 不能为空")
    @Size(max = 64, message = "userId 最长 64 个字符")
    private String userId;

    @NotBlank(message = "orderId 不能为空")
    @Size(min = 6, max = 64, message = "orderId 长度必须在 6 到 64 个字符之间")
    @Pattern(
            regexp = "^[A-Za-z0-9_-]+$",
            message = "orderId 只能包含字母、数字、下划线和短横线")
    private String orderId;
}
