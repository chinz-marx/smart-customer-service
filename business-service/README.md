# Business Service

智能客服的 Java 业务服务。Python 负责理解用户、管理会话和编排流程；本服务只负责：

- 校验真实业务参数与访问权限
- 通过 MyBatis-Plus 查询 PostgreSQL
- 执行确定性的业务规则
- 返回可直接展示的 Tool 结果
- 记录不含聊天原文的 Tool 调用审计
- 管理知识版本、人工审批和可靠发布Outbox

当前第一条业务闭环是订单查询：`POST /api/internal/tools/orders/query`。

## 技术版本

- JDK 21
- Spring Boot 4.0.7
- MyBatis-Plus 3.5.17
- Lombok
- PostgreSQL 18
- Flyway

## 数据库边界

Java 与 Python 使用同一个 `smart_customer_service` 数据库，但 Java 只拥有
`business` schema。应用启动时 Flyway 会执行：

`src/main/resources/db/migration/V1__create_business_order_tables.sql`
`src/main/resources/db/migration/V2__create_knowledge_base_tables.sql`
`src/main/resources/db/migration/V3__seed_knowledge_base.sql`

本地联调演示数据位于 `scripts/demo-data.sql`，生产环境不要执行该文件。

## 环境变量

Spring Boot 默认不会读取 `.env` 文件。请把 `.env.example` 中的变量设置到操作系统、
IDE 启动配置或部署平台中。数据库密码和内部令牌禁止写进 `application.yml`。

Python 调用 Java 时，`X-Internal-Token` 必须与 Java 的 `TOOL_INTERNAL_TOKEN` 相同；
`userId` 必须来自可信登录态，不能从用户聊天文字中提取。

## Windows 构建与启动

在仓库根目录执行：

```powershell
$env:JAVA_HOME = 'E:\workSoft\jdk21\jdk-21.0.6'
$env:BUSINESS_DATABASE_PASSWORD = '你的本地数据库密码'
$env:TOOL_INTERNAL_TOKEN = '你的内部调用令牌'

& 'E:\workSoft\apache-maven-3.8.8\bin\mvn.cmd' `
  -f business-service\pom.xml `
  clean test

& 'E:\workSoft\apache-maven-3.8.8\bin\mvn.cmd' `
  -f business-service\pom.xml `
  spring-boot:run
```

在运行服务的终端按 `Ctrl+C` 即可停止。

## Linux 构建与启动

```bash
export JAVA_HOME=/opt/jdk-21
export BUSINESS_DATABASE_PASSWORD='你的本地数据库密码'
export TOOL_INTERNAL_TOKEN='你的内部调用令牌'

mvn -f business-service/pom.xml clean test
mvn -f business-service/pom.xml spring-boot:run
```

在运行服务的终端按 `Ctrl+C` 即可停止。

## 调用示例

```http
POST /api/internal/tools/orders/query HTTP/1.1
Host: 127.0.0.1:8081
Content-Type: application/json
X-Internal-Token: 这里填写与 TOOL_INTERNAL_TOKEN 相同的值
X-Request-Id: request-demo-001

{
  "sessionId": "session-demo-001",
  "userId": "USER_10001",
  "orderId": "ORDER_123456"
}
```

返回数据中的 `data.answer` 是 Java 业务系统生成的完整话术。Python 应直接返回该字段，
不再调用最终回答 LLM。

## 目录说明

- `common`：统一响应、异常、requestId、内部令牌校验
- `order/api`：订单 Tool HTTP 接口及请求/响应 DTO
- `order/domain`：订单实体、状态和业务规则
- `order/mapper`：MyBatis-Plus 数据访问接口
- `order/service`：订单查询业务流程
- `audit`：Tool 调用审计
- `knowledge`：知识CRUD、版本审批、Outbox和Python索引同步
- `db/migration`：由 Flyway 执行的正式建表 SQL
