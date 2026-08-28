# Smart Customer Service

一个采用 **Vue 3 + FastAPI + Spring Boot + PostgreSQL + Redis Search** 构建的智能客服系统。

项目把“语言理解”和“真实业务执行”拆成两条边界清晰的链路：Python负责意图识别、知识检索、对话编排和向量计算；Java负责订单、积分、权益、退款等确定性业务，以及知识版本、审批、发布和审计。

系统目前已经形成以下完整闭环：

- 客服流式对话、多轮会话和历史记录；
- Java MCP业务Tool调用与公共缺参追问；
- 知识草稿、审批、分片、向量发布和Redis索引重建；
- 确定性常见问题直答；
- 低质量问题收集、知识草稿生成和回归测试集；
- 知识发布自动验收与YAML离线基准评测。

> 当前仓库是可运行的工程化演示项目。登录认证、真实支付网关和生产部署基础设施仍需要根据实际企业环境接入。

## 目录

- [界面预览](#界面预览)
- [设计目标](#设计目标)
- [功能清单](#功能清单)
- [总体架构](#总体架构)
- [核心流程](#核心流程)
- [模块职责](#模块职责)
- [技术栈](#技术栈)
- [数据设计](#数据设计)
- [Redis设计](#redis设计)
- [主要接口](#主要接口)
- [快速开始](#快速开始)
- [操作手册](#操作手册)
- [测试与验证](#测试与验证)
- [常见问题](#常见问题)
- [安全设计](#安全设计)
- [项目结构](#项目结构)
- [当前限制](#当前限制)

## 界面预览

### 客服工作台

支持流式对话、历史会话续聊、常见问题直答、推荐问题、文字/语音输入、表情和会话评价。

![客服工作台](docs/images/customer-service.png)

### 知识管理

集中维护知识分类、草稿版本、审批状态、发布时间和发布后的停用操作。

![知识管理](docs/images/knowledge-management.png)

### 问题收集

聚合负反馈、投诉、转人工、Tool失败和知识未命中问题，支持筛选、审核与转知识草稿。

![问题收集](docs/images/problem-collection.png)

### 评测中心

展示问题学习测试集、单条评测原因、知识发布自动验收以及YAML离线基准评测。

![评测中心](docs/images/evaluation-center.png)

## 设计目标

### 1. AI不直接操作核心业务数据

大模型只负责理解用户表达和制定执行计划。订单、积分、奖励、权益和退款全部通过Java MCP Tool执行，业务规则、权限校验和数据库事务仍由Java控制。

### 2. PostgreSQL是主数据源

知识内容、版本、审批、会话、问题学习和评测记录均以PostgreSQL为准。Redis只保存可重建的会话状态、检索副本、向量索引和短期缓存。

### 3. 知识发布必须经过审批

编辑知识不会直接覆盖线上内容。每次修改生成新版本，提交审批后由其他操作人通过或驳回；审批通过后再由Outbox可靠发布到Redis Search。

### 4. 实时数据与规则知识分开处理

- “我的订单到哪了”属于实时业务，调用Tool；
- “发货后还能取消吗”属于规则咨询，查询知识库；
- “查订单状态，另外发货后还能不能取消”属于组合请求，同时执行Tool和知识检索。

### 5. 缓存失效必须可恢复

Redis重启或索引丢失后，可以从PostgreSQL中的当前已发布版本执行全量重建，不把Redis当作不可替代的数据源。

### 6. 低质量回答形成学习闭环

“没帮助”、低评分、投诉、转人工、Tool失败和知识未命中会进入问题收集。人工审核后可以生成知识草稿和测试用例，再经过知识审批与发布验收进入线上知识库。

## 功能清单

### 客服端

- SSE流式回答；
- 多轮对话上下文；
- 历史对话列表、加载更多和刷新；
- 点击历史记录继续咨询；
- 新建和清空对话；
- 加载、空数据和错误重试状态；
- 移动端历史抽屉；
- 推荐问题快捷发送；
- 常见问题确定性直答；
- 单条回答“有帮助/没帮助”反馈；
- 会话五星评价；
- 表情选择并在光标位置插入；
- PC端与移动端响应式布局；
- 已移除图片和文件上传入口。

### AI编排

- 意图识别、情绪和风险识别；
- `direct`、`system`、`tool`、`knowledge`、`composite`路由；
- Tool和知识需求独立判断；
- Redis语义召回Top K Tool，降低提示词体积；
- Tool召回超时后完整目录降级；
- 基于MCP Schema的公共参数解析；
- 缺少业务参数时自动追问；
- 下一轮自然语言槽位补全；
- 用户切换话题后清理旧Tool参数；
- 系统可信注入`sessionId`、`userId`和`requestId`；
- 知识库、LangCache和回答模型分层降级。

### Java业务Tool

| Tool | 能力 | 关键约束 |
| --- | --- | --- |
| `order_query` | 查询订单状态、物流节点和预计进度 | 只能查询当前登录用户订单 |
| `points_query` | 查询积分余额和即将到期积分 | 用户身份由系统注入 |
| `reward_query` | 查询奖励发放状态 | 活动名称可选 |
| `benefits_query` | 查询会员等级、成长值和权益 | 不承担通用规则解释 |
| `refund_query` | 查询退款进度和金额 | 需要订单号 |
| `refund_quote` | 校验退款资格并试算金额 | 只读，不创建退款单 |
| `refund_apply` | 正式创建退款申请 | 必须先试算并由用户明确确认 |

### 知识管理

- 知识分页、搜索和分类筛选；
- 待审批、已发布等视图隔离；
- 新增、编辑、保存草稿和申请停用；
- Python端知识分片；
- 标准问法生成和编辑；
- 申请人与审批人隔离；
- 表格内通过、驳回和撤销；
- Outbox异步发布；
- Redis知识索引全量重建；
- 已发布版本与待审批版本并存。

### 常见问题

- 只展示已发布知识中的标准问法；
- 默认展示5条；
- 相同问题或相同答案去重；
- Java直接返回确定性答案，不调用LLM；
- Redis映射优先，PostgreSQL分片降级；
- Java SSE流式输出，避免问题和答案重复追加。

### 问题学习

- 聚合负反馈、投诉、转人工、Tool失败和RAG未命中信号；
- 按语义聚类并统计问题频次和影响用户数；
- 收集中、待审核、通过、驳回、转知识和忽略状态；
- 手动提交待审核并二次确认；
- 保存人工标准回答；
- LLM生成可编辑的成长回答；
- 生成知识标题、标签、标准问法和回归问题；
- 转换为知识草稿并进入知识审批；
- 全过程保留人工审核记录。

### 评测中心

- 问题学习测试集；
- 按知识和版本分组展示；
- 单条通过状态与未通过原因；
- 知识发布自动验收；
- Recall@1、Recall@3、阈值召回和负样本误命中率；
- YAML离线基准数据集；
- 后台线程执行知识召回或意图识别评测；
- 评测任务状态轮询和历史记录；
- JSON与Markdown报告下载；
- 报告名称包含数据集、类型、样本数、状态和完成时间。

## 总体架构

```mermaid
flowchart LR
    U[用户/运营人员]

    subgraph FE[Vue 3 前端]
        C[客服页面]
        A[管理后台]
    end

    subgraph PY[Python AI层]
        CHAT[聊天与SSE]
        ROUTER[语义理解与执行规划]
        RAG[知识检索]
        LEARN[问题学习]
        EVAL[AI评测]
        PUB[分片/Embedding/索引发布]
    end

    subgraph JAVA[Java业务层]
        MCP[MCP Server：7个Tool]
        BIZ[订单/积分/权益/退款]
        KB[知识版本与审批]
        FAQ[确定性FAQ]
        OUTBOX[知识发布Outbox]
        AUDIT[业务审计]
    end

    PG[(PostgreSQL 18)]
    REDIS[(Redis Search)]
    MODEL[理解/回答/Embedding模型]
    NACOS[Nacos，可选]

    U --> C
    U --> A
    C --> CHAT
    A --> KB
    A --> LEARN
    A --> EVAL

    CHAT --> ROUTER
    ROUTER --> RAG
    ROUTER --> MCP
    ROUTER --> MODEL
    RAG --> REDIS
    RAG --> MODEL

    MCP --> BIZ
    BIZ --> PG
    MCP --> AUDIT
    AUDIT --> PG

    KB --> PG
    KB --> OUTBOX
    OUTBOX --> PUB
    PUB --> REDIS
    PUB --> PG

    C --> FAQ
    FAQ --> REDIS
    FAQ --> PG

    CHAT --> PG
    CHAT --> REDIS
    LEARN --> PG
    EVAL --> PG
    EVAL --> REDIS

    ROUTER -.提示词/Tool发现.-> NACOS
    MCP -.注册.-> NACOS
```

### 分层职责

| 层 | 职责 | 不负责 |
| --- | --- | --- |
| Vue前端 | 展示、交互、SSE消费、管理后台 | 业务规则和AI判断 |
| Python AI层 | 意图、路由、槽位、RAG、Embedding、评测 | 直接修改核心业务数据 |
| Java业务层 | 业务校验、事务、审批、Tool、审计 | 自由生成业务事实 |
| PostgreSQL | 所有长期主数据 | 向量近邻检索 |
| Redis | 会话状态、向量索引、映射、锁和短期缓存 | 作为唯一主数据源 |

## 核心流程

### 用户提问流程

```mermaid
flowchart TD
    Q[用户输入问题] --> H[读取最近对话和Redis会话状态]
    H --> T[Redis召回候选MCP Tool]
    T --> I[LLM意图识别与执行规划]
    I --> RT{route_type}

    RT -->|direct/system| D[直接生成或返回固定回答]
    RT -->|knowledge| K[生成Embedding并查询知识索引]
    RT -->|tool| S[按MCP Schema解析参数]
    RT -->|composite| BOTH[同时准备Tool与知识检索]

    S --> M{参数完整?}
    M -->|否| ASK[保存active_tool并追问缺失参数]
    M -->|是| CALL[调用Java MCP Tool]

    BOTH --> CALL
    BOTH --> K

    K --> KH{命中已发布知识?}
    KH -->|是| KA[使用知识答案]
    KH -->|否| LLM[回答模型降级]

    CALL --> MERGE[合并Tool结果和知识]
    KA --> MERGE
    LLM --> OUT[SSE流式输出]
    D --> OUT
    ASK --> OUT
    MERGE --> OUT
    OUT --> SAVE[保存会话、消息和学习信号]
```

### 多轮参数补全

```mermaid
sequenceDiagram
    participant U as 用户
    participant P as Python编排
    participant R as Redis状态
    participant J as Java MCP

    U->>P: 查订单
    P->>P: 识别 order_query
    P->>R: active_tool=order_query，等待orderId
    P-->>U: 请提供订单号
    U->>P: ORDER_20260809001 是我的订单号
    P->>P: 从原文提取并校验orderId
    P->>R: 写入tool_arguments.orderId
    P->>J: order_query + 可信上下文
    J-->>P: 订单状态和物流信息
    P->>R: 完成后清理旧Tool状态
    P-->>U: 流式返回查询结果
```

如果用户在等待参数期间明确切换到其他问题，编排器会清理旧`active_tool`和旧参数，重新执行完整意图识别，避免再次查询旧订单。

### 知识发布流程

```mermaid
flowchart TD
    EDIT[编辑知识] --> DRAFT[保存草稿]
    DRAFT --> SPLIT[Python生成原子分片]
    SPLIT --> QUESTION[生成/编辑标准问法]
    QUESTION --> SUBMIT[提交审批]
    SUBMIT --> CHECK{其他操作人审批}
    CHECK -->|驳回| DRAFT
    CHECK -->|通过| CURRENT[Java切换当前发布版本]
    CURRENT --> OUTBOX[写入Outbox事件]
    OUTBOX --> WORKER[Java Worker调用Python]
    WORKER --> EMBED[生成分片和问法向量]
    EMBED --> INDEX[写入Redis Hash和Search索引]
    INDEX --> CALLBACK[回写分片同步状态]
```

### 问题学习和评测流程

```mermaid
flowchart TD
    SIGNAL[负反馈/投诉/转人工/Tool失败/RAG未命中]
    SIGNAL --> CLUSTER[Embedding聚类与频次统计]
    CLUSTER --> THRESHOLD{达到审核门槛?}
    THRESHOLD -->|否| COLLECT[继续收集]
    THRESHOLD -->|是| REVIEW[进入待审核]
    REVIEW --> ANSWER[人工维护标准回答]
    ANSWER --> PACKAGE[生成知识草稿和测试问题]
    PACKAGE --> KBAPPROVAL[知识审批]
    KBAPPROVAL -->|驳回| ANSWER
    KBAPPROVAL -->|通过| RELEASE[发布Redis知识索引]
    RELEASE --> GATE[自动发布验收]

    YAML[YAML固定数据集] --> OFFLINE[离线基准评测]
    OFFLINE --> REPORT[JSON/Markdown报告]
```

## 模块职责

### `frontend`

Vue单页应用，同时承载客服页面和管理后台。

- `/api/*`由Vite代理到Python的`8000`端口；
- `/business-api/*`由Vite重写后代理到Java的`8081`端口；
- 客服回答与FAQ回答均使用SSE消费增量内容；
- 管理后台包含知识管理、问题收集、评测中心和审批中心。

### `backend`

Python 3.12 FastAPI服务。

- `app/orchestrator.py`：主编排器；
- `app/understanding.py`：意图理解；
- `app/tools/`：MCP客户端、Tool召回和公共参数解析；
- `app/retrieval/`：知识分片、Embedding、发布和语义检索；
- `app/learning/`：问题学习、回答和知识包生成；
- `app/evaluation/`：发布验收和离线评测；
- `app/persistence/`：会话、消息、反馈和工单持久化。

### `business-service`

JDK 21 Spring Boot服务。

- `order/`：订单查询；
- `customer/`：积分、奖励、权益和退款进度；
- `aftersales/`：退款试算和退款申请；
- `knowledge/`：知识CRUD、版本、审批、FAQ和Outbox；
- `learning/`：问题审核、测试用例和评测结果；
- `audit/`：MCP Tool调用审计；
- `db/migration/`：Flyway数据库迁移。

## 技术栈

| 领域 | 技术 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite 6、Lucide Icons |
| Python | Python 3.12、FastAPI、SQLAlchemy 2、asyncpg、Pydantic、httpx |
| AI编排 | LangChain 1.x、MCP Python SDK、结构化JSON规划 |
| Java | JDK 21、Spring Boot 3.5.8、Spring AI MCP、MyBatis-Plus |
| 数据库 | PostgreSQL 18、Flyway |
| 缓存/检索 | Redis、Redis Search、HNSW、COSINE |
| 服务发现 | Nacos 3.x，可选 |
| 模型 | OpenAI兼容接口；当前支持独立理解、回答和Embedding模型 |
| 评测 | YAML数据集、JSON报告、Markdown报告 |

## 数据设计

### `public`会话域

| 表 | 用途 |
| --- | --- |
| `chat_conversation` | 客服会话 |
| `chat_message` | 用户和助手消息 |
| `chat_feedback` | 单条反馈和星级评价 |
| `service_ticket` | 转人工工单与上下文快照 |

### `business`业务与知识域

| 表组 | 主要表 |
| --- | --- |
| 订单与审计 | `business_order`、`tool_call_audit` |
| 客户账户 | `customer_points_account`、`customer_reward_record`、`customer_member_profile`、`customer_refund_record` |
| 退款 | `order_refund_pricing`、`order_refund_item`、`refund_quote_snapshot`、`after_sales_order`、`payment_refund_task` |
| 知识 | `kb_category`、`kb_knowledge`、`kb_knowledge_version`、`kb_knowledge_chunk`、`kb_knowledge_question` |
| 审批与发布 | `kb_approval`、`kb_operation_log`、`kb_outbox_event` |

### `learning`学习与评测域

| 表 | 用途 |
| --- | --- |
| `learning_signal` | 原始学习信号 |
| `learning_problem` | 聚类后的问题 |
| `learning_sample` | 问题样本 |
| `learning_problem_review` | 人工审核记录 |
| `learning_evaluation_case` | 问题学习测试用例 |
| `learning_evaluation_run` | 发布评测批次 |
| `learning_evaluation_case_result` | 单条评测结果 |

Java Flyway当前包含`V1`至`V15`共15个迁移文件。生产环境应通过迁移管理表结构，不要手工删除业务表。

## Redis设计

| Key或索引 | 类型 | 用途 |
| --- | --- | --- |
| `cs:session:{sessionId}` | Hash/JSON状态 | 当前意图、活动Tool和待补参数 |
| `cs:knowledge:doc:*` | Hash | 已发布知识分片及标准问法向量副本 |
| `cs:knowledge:question-map:{questionId}` | String | 标准问法ID到知识文档Key的映射 |
| `idx:cs:knowledge` | Search索引 | 已发布知识向量检索 |
| `cs:mcp:tool:*` | Hash | MCP Tool Schema语义副本 |
| `idx:cs:mcp-tools` | Search索引 | Tool候选召回 |
| `cs:langcache:entry:*` | Hash + TTL | 高频问题的短期模型答案 |
| `idx:cs:langcache` | Search索引 | LangCache语义检索 |
| `cs:langcache:gap:*` | Hash/Set + TTL | 未命中问题聚类和会话去重计数 |

Redis中的知识和Tool索引都是加速副本。Redis重启后，应分别通过知识全量重建和MCP目录重新同步恢复。

## 主要接口

### Python API：`http://127.0.0.1:8000`

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/health` | Python依赖健康检查 |
| POST | `/api/chat/stream` | 客服SSE流式对话 |
| POST | `/api/chat` | 非流式兼容接口 |
| POST | `/api/feedback` | 保存用户反馈 |
| GET | `/api/conversations` | 历史会话列表 |
| GET | `/api/conversations/{id}/messages` | 历史消息 |
| POST | `/api/knowledge/chunks/split` | 知识分片 |
| POST | `/api/knowledge/questions/generate` | 生成标准问法 |
| POST | `/api/internal/knowledge/publish` | Java Outbox调用的索引发布接口 |
| POST | `/api/internal/knowledge/delete` | 删除Redis知识副本 |
| POST | `/api/learning/answers/generate` | 生成问题回答草稿 |
| POST | `/api/learning/packages/generate` | 生成知识草稿和测试集 |
| GET | `/api/evaluation/benchmarks/datasets` | 离线数据集列表 |
| POST | `/api/evaluation/benchmarks/runs` | 启动离线评测 |

### Java API：`http://127.0.0.1:8081`

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/actuator/health` | Java健康检查 |
| POST | `/mcp` | MCP Streamable HTTP入口 |
| GET | `/api/customer/faqs` | 常见问题列表 |
| POST | `/api/customer/faqs/{questionId}/answer/stream` | FAQ确定性流式回答 |
| GET/POST/PUT/DELETE | `/api/admin/knowledge/**` | 知识管理 |
| POST | `/api/admin/knowledge/reindex` | 重建全部已发布知识索引 |
| GET/POST | `/api/admin/knowledge/approvals/**` | 知识审批 |
| GET/PUT/POST | `/api/admin/learning/problems/**` | 问题审核与转知识 |
| GET | `/api/admin/learning/evaluation-cases` | 问题学习测试集 |
| GET | `/api/admin/learning/evaluation-runs` | 发布评测记录 |

内部业务接口和管理写接口需要对应的内部令牌或`X-Operator-Id`。正式生产部署时应由认证网关注入身份，而不是信任浏览器自由填写。

## 快速开始

### 环境要求

- JDK 21；
- Maven 3.8+；
- Python 3.12；
- [uv](https://docs.astral.sh/uv/)；
- Node.js 20+；
- pnpm或npm；
- PostgreSQL 18；
- 支持RediSearch的Redis实例；
- Nacos 3.x，可选；
- 理解模型、回答模型和Embedding模型的API Key，可使用本地降级模式开发。

### 1. 创建数据库

```sql
CREATE DATABASE smart_customer_service;
```

Java服务启动时会由Flyway创建`business`、`learning`以及会话相关表。首次纯Python内存联调可以不连接数据库，但完整功能必须使用PostgreSQL。

### 2. 配置Java环境变量

Spring Boot不会自动读取`business-service/.env.example`，请把变量配置到操作系统、IDE或部署平台。

Windows PowerShell示例：

```powershell
$env:BUSINESS_DATABASE_URL = 'jdbc:postgresql://127.0.0.1:5432/smart_customer_service'
$env:BUSINESS_DATABASE_USERNAME = 'postgres'
$env:BUSINESS_DATABASE_PASSWORD = 'your-password'
$env:BUSINESS_REDIS_URL = 'redis://127.0.0.1:6379/0'
$env:TOOL_INTERNAL_TOKEN = 'replace-with-a-long-random-token'
$env:BUSINESS_SERVER_PORT = '8081'
```

如果启用Nacos，再配置：

```powershell
$env:NACOS_SERVER_ADDR = 'http://127.0.0.1:8848'
$env:NACOS_NAMESPACE = 'public'
$env:NACOS_USERNAME = 'nacos-user'
$env:NACOS_PASSWORD = 'nacos-password'
$env:NACOS_MCP_REGISTER_ENABLED = 'true'
$env:NACOS_MCP_SERVER_HOST = '127.0.0.1'
$env:NACOS_MCP_SERVER_PORT = '8081'
```

### 3. 启动Java业务服务

建议先启动Java，再启动Python，避免Python初始化MCP时连接不到`8081`。

```powershell
mvn -f business-service/pom.xml clean test
mvn -f business-service/pom.xml spring-boot:run
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8081/actuator/health
```

预期：

```json
{"status":"UP"}
```

### 4. 配置并启动Python AI服务

```powershell
Copy-Item backend/.env.example backend/.env
```

至少检查以下配置：

```env
APP_PORT=8000
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
PERSISTENCE_BACKEND=postgres
DATABASE_URL=postgresql+asyncpg://postgres:your-password@127.0.0.1:5432/smart_customer_service
DATABASE_AUTO_CREATE_TABLES=false

BUSINESS_TOOL_INTERNAL_TOKEN=replace-with-a-long-random-token
MCP_ENABLED=true
MCP_SERVER_URL=http://127.0.0.1:8081/mcp

SEMANTIC_SEARCH_ENABLED=true
TOOL_RETRIEVAL_ENABLED=true
```

`BUSINESS_TOOL_INTERNAL_TOKEN`必须与Java的`TOOL_INTERNAL_TOKEN`完全一致。

安装依赖并启动：

```powershell
Set-Location backend
uv sync --python 3.12
uv run python -m app.main
```

验证：

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/health
```

健康结果中重点检查：

- `session_store_status=ok`；
- `persistence_status=ok`；
- `semantic_search_status=ok`；
- `mcp_status=ok`；
- `mcp_tools`包含7个Tool。

### 5. 启动前端

```powershell
Set-Location frontend
corepack pnpm install --frozen-lockfile
corepack pnpm dev
```

访问：

- 客服页面：`http://127.0.0.1:5173/`
- 管理后台：`http://127.0.0.1:5173/#/knowledge`

### 推荐启动顺序

```text
PostgreSQL / Redis / Nacos（可选）
    → Java 8081
    → Python 8000
    → Vue 5173
```

## 操作手册

### 客服咨询

1. 打开客服页面；
2. 输入问题并按Enter发送，Shift+Enter换行；
3. 需要订单号等参数时，根据客服提示继续补充；
4. 点击左侧历史记录可继续原会话；
5. 点击“新建对话”开始新会话；
6. 点击表情按钮可在当前光标位置插入表情；
7. 回答完成后可以提交单条反馈或会话星级。

### 使用常见问题

1. 客服页加载已发布知识的标准问法；
2. 点击某条标准问法；
3. 前端把`questionId`发送给Java；
4. Java先读取`cs:knowledge:question-map:{questionId}`；
5. Redis命中时直接读取知识Hash；
6. Redis未命中时回退PostgreSQL分片；
7. Java以SSE形式直接返回确定性答案，全程不调用LLM。

### 新增知识

1. 进入“知识管理”；
2. 点击新增知识；
3. 选择分类和意图编码；
4. 填写标题和正文；
5. 检查Python生成的分片和标准问法；
6. 可以先“保存草稿”，也可以直接“提交审批”；
7. 提交后等待其他操作人审批。

### 审批知识

1. 切换到与申请人不同的操作人ID；
2. 进入“审批中心”或待审批视图；
3. 检查正文、分类、意图、分片和标准问法；
4. 在表格操作区点击通过或驳回；
5. 通过后Java写入Outbox；
6. Python完成Embedding和Redis发布后，该版本成为可检索知识。

申请人不能审批自己的申请，这是系统的职责分离规则，不是页面故障。

### 保存和修改知识草稿

- “保存草稿”只保存当前编辑内容，不创建审批单；
- “提交审批”会创建待审批版本；
- 已存在待审批版本时，继续编辑的是该待审批版本；
- 已发布页面只展示当前线上版本，不应混入待审批数据；
- 停用知识同样走审批，不会直接物理删除。

### 问题收集

1. 进入“问题收集”；
2. 按状态筛选收集中、待审核等问题；
3. 收集中的问题可以手动提交待审核；
4. 审核人员查看真实样本和触发原因；
5. 保存人工标准回答，或让LLM生成可编辑草稿；
6. 选择通过、驳回或忽略；
7. 对通过问题生成知识草稿和测试问题；
8. 确认后提交知识审批。

### 离线基准评测

1. 进入“评测中心”；
2. 在“离线基准评测”选择YAML数据集；
3. 点击“开始评测”；
4. Python在后台线程执行数据集；
5. 页面轮询并展示等待、执行中或完成状态；
6. 完成后查看通过状态和指标；
7. 根据需要下载JSON或Markdown报告。

离线基准评测与单个知识版本的自动发布验收是两套独立流程，不要把固定YAML数据集与知识草稿测试集混为一谈。

### Redis知识索引重建

当以下数据均为0时，说明知识检索副本已经丢失：

```text
cs:knowledge:doc:*
cs:knowledge:question-map:*
idx:cs:knowledge num_docs
```

执行：

```http
POST /api/admin/knowledge/reindex HTTP/1.1
Host: 127.0.0.1:8081
X-Operator-Id: system-reindex
```

重建流程：

```text
Java读取PostgreSQL当前已发布版本
    → 写入Outbox
    → Worker调用Python发布接口
    → Python生成Embedding
    → 写入Redis Hash和向量索引
```

重建后校验：

```text
PG当前发布分片数 + 标准问法数
    = cs:knowledge:doc:* 数量
    = idx:cs:knowledge num_docs

PG当前标准问法数
    = cs:knowledge:question-map:* 数量
```

## 测试与验证

### Python单元测试

```powershell
Set-Location backend
uv run pytest
```

### Java测试

```powershell
mvn -f business-service/pom.xml test
```

### 前端类型检查和构建

```powershell
Set-Location frontend
corepack pnpm build
```

### 意图难例评测

```powershell
Set-Location backend
uv run python scripts/evaluate_intents.py `
  --dataset evaluation/intent_hard_cases.yaml `
  --mode hybrid `
  --concurrency 2 `
  --check-thresholds
```

### 知识检索验证

```powershell
Set-Location backend
uv run python scripts/verify_semantic_search.py
uv run python scripts/verify_chat_api.py
```

真实模型测试可能产生费用，默认测试不应调用真实LLM。只有明确需要时才设置`RUN_LIVE_LLM_TESTS=1`。

## 常见问题

### `relation "chat_conversation" does not exist`

原因：PostgreSQL会话表没有迁移成功，或者Python连接到了错误数据库。

检查：

1. Java启动日志中的Flyway版本；
2. `DATABASE_URL`与`BUSINESS_DATABASE_URL`是否指向同一个数据库；
3. `public.chat_conversation`等V9迁移表是否存在。

### `Tool 语义召回失败，已回退完整目录: TimeoutError`

含义：Embedding调用和Redis Tool向量检索的总耗时超过`TOOL_RETRIEVAL_TIMEOUT_SECONDS`，系统因此把完整Tool目录交给意图模型。

排查顺序：

1. 单独记录Embedding耗时；
2. 单独记录Redis Search耗时；
3. 检查`idx:cs:mcp-tools num_docs`是否为7；
4. 调整超时，而不是无限增大；
5. 为高频明确表达保留快速规则召回。

### `Attempted to exit cancel scope in a different task`

这是MCP Python SDK/AnyIO在Streamable HTTP连接清理阶段的任务归属异常，通常发生在Java MCP不可访问或Python启动中途失败之后。

处理：

1. 先确认Java的`8081`端口和`/actuator/health`；
2. 再启动Python；
3. 查看该异常上方的第一个Traceback，它才是启动失败的原始原因；
4. 不要只捕获并忽略清理异常，MCP连接的创建和关闭应由同一个长期任务负责。

### 评测提示“找不到已发布目标知识”

YAML中的目标知识标题必须能在PostgreSQL当前已发布版本中找到。知识还在草稿或待审批状态时，评测脚本不会把它当作已发布知识。

### FAQ可以展示，但点击后回答失败

检查：

- `cs:knowledge:question-map:{questionId}`是否存在；
- 映射指向的`cs:knowledge:doc:*`是否存在；
- PostgreSQL中的`chunk_id`和当前发布版本是否一致；
- Java是否能连接Redis和PostgreSQL。

## 安全设计

- API Key、数据库密码、Redis密码和Nacos凭证只能存放在本地`.env`或部署平台；
- `.env`不得提交到Git；
- Java与Python之间使用共享内部令牌；
- `userId`来自可信登录态，不能从聊天原文提取；
- MCP的`sessionId`、`userId`和`requestId`由Python系统注入；
- Tool执行前使用JSON Schema校验参数；
- 高风险退款转人工审核；
- 退款申请使用幂等键和Redis分布式锁；
- Tool审计不保存不必要的聊天原文；
- 申请人与审批人分离；
- 知识删除采用停用审批，不进行直接物理删除。

## 项目结构

```text
smart-customer-service/
├─ frontend/                       # Vue客服端和管理后台
│  ├─ src/components/
│  │  ├─ ChatWorkspace.vue         # 客服工作区
│  │  ├─ LeftPanel.vue             # 历史会话和FAQ
│  │  ├─ KnowledgeAdmin.vue        # 知识与审批后台
│  │  ├─ ProblemCollectionView.vue # 问题收集
│  │  └─ EvaluationCenterView.vue  # 评测中心
│  └─ vite.config.ts               # Python/Java双代理
├─ backend/                        # Python AI服务
│  ├─ app/
│  │  ├─ tools/                    # MCP客户端与Tool召回
│  │  ├─ retrieval/                # 分片、Embedding与RAG
│  │  ├─ learning/                 # 问题学习
│  │  ├─ evaluation/               # 发布验收与离线评测
│  │  └─ persistence/              # 会话持久化
│  ├─ evaluation/                  # YAML数据集与报告
│  ├─ scripts/                     # 验证和评测脚本
│  ├─ pyproject.toml
│  └─ uv.lock
├─ business-service/               # Java业务和MCP服务
│  ├─ src/main/java/.../business/
│  │  ├─ order/
│  │  ├─ customer/
│  │  ├─ aftersales/
│  │  ├─ knowledge/
│  │  ├─ learning/
│  │  └─ audit/
│  ├─ src/main/resources/db/migration/
│  └─ pom.xml
└─ README.md
```

## 当前限制

- 当前使用固定演示用户，尚未接入正式登录、租户和RBAC；
- 操作人ID目前由前端传递，生产环境必须由认证网关注入；
- 退款支付网关为Mock实现；
- 语音按钮目前只是页面入口，尚未接入ASR；
- 不支持图片和文件上传；
- Java与Python的异步评测任务尚未引入企业MQ；
- Nacos不可用时使用本地配置和MCP备用地址；
- 模型质量、Embedding阈值和评测门槛必须根据真实业务数据重新标定；
- 当前README中的本地启动方式适合开发联调，生产环境仍需补充网关、TLS、容器编排、监控告警和密钥管理。

## 延伸文档

- [Java业务服务说明](./business-service/README.md)
- [Python服务说明](./backend/README.md)
