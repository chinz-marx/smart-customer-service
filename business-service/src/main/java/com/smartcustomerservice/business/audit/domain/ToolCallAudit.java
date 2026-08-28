package com.smartcustomerservice.business.audit.domain;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;
import lombok.AllArgsConstructor;
import lombok.Builder;
import lombok.Getter;
import lombok.NoArgsConstructor;
import lombok.Setter;

import java.time.OffsetDateTime;

/** 保存 Python 调用 Java Tool 的最小审计信息，不保存聊天原文。 */
@Getter
@Setter
@Builder
@NoArgsConstructor
@AllArgsConstructor
@TableName(value = "tool_call_audit", schema = "business")
public class ToolCallAudit {
    @TableId(type = IdType.AUTO)
    private Long id;
    private String requestId;
    private String sessionId;
    private String toolName;
    private String userId;
    private String resourceId;
    private String resultCode;
    private Boolean success;
    private Long durationMs;
    private OffsetDateTime createdAt;
}
