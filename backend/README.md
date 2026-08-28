# 智能客服Python后端

基于Python 3.12、FastAPI、LangChain 1.x、redis-py和SQLAlchemy 2.x。依赖由uv管理，代码同时支持Windows和Linux。

## 当前存储设计

- Redis 7.2：保存当前意图、槽位、轮次等短期会话状态，默认TTL为30分钟。
- PostgreSQL 18：保存聊天会话、消息、用户反馈和人工工单。
- 内存模式：不需要Redis和PostgreSQL即可完成开发自测，但进程退出后数据会消失。

PostgreSQL包含四张表：

- `chat_conversation`：一次完整客服对话。
- `chat_message`：用户和AI的每条消息。
- `chat_feedback`：有帮助、没帮助、星级和意见。
- `service_ticket`：转人工时生成的工单和上下文快照。

## 安装Python依赖

```powershell
cd backend
uv sync --python 3.12
```

`requirements.txt`只用于不使用uv的兼容场景，日常开发以`pyproject.toml`和`uv.lock`为准。

## 无外部服务自测

`.env`中保持下面配置：

```env
SESSION_STORE_BACKEND=memory
PERSISTENCE_BACKEND=memory
DEMO_USER_ID=demo-user-001
```

Windows和Linux使用相同的启动方式：

```powershell
cd backend
uv run python -m app.main
```

`APP_HOST`、`APP_PORT`和`APP_RELOAD`从`.env`读取。

## 启用Redis和PostgreSQL

安装并启动Redis 7.2和PostgreSQL 18后，先创建数据库`smart_customer_service`，再修改`.env`：

```env
SESSION_STORE_BACKEND=redis
REDIS_URL=redis://127.0.0.1:6379/0
REDIS_SESSION_TTL_SECONDS=1800
REDIS_SESSION_KEY_PREFIX=cs:session:

PERSISTENCE_BACKEND=postgres
DATABASE_URL=postgresql+asyncpg://postgres:你的密码@127.0.0.1:5432/smart_customer_service
DATABASE_ECHO=false
DATABASE_AUTO_CREATE_TABLES=true
```

首次开发联调可以把`DATABASE_AUTO_CREATE_TABLES`设为`true`，SQLAlchemy会自动创建四张表。确认建表完成后可改回`false`。生产环境后续应接入Alembic迁移，不建议长期依赖自动建表。

如果数据库密码包含`@`、`:`、`/`等字符，需要先做URL编码。

## 模型配置

```env
DOUBAO_API_KEY=你的API Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=你的模型名或endpoint id
DOUBAO_TEMPERATURE=0.3
DOUBAO_TIMEOUT_SECONDS=15
DOUBAO_MAX_RETRIES=1

# hybrid：DeepSeek理解优先，失败时使用关键词分类器
UNDERSTANDING_MODE=hybrid
UNDERSTANDING_API_KEY=你的DeepSeek API Key
UNDERSTANDING_BASE_URL=https://api.deepseek.com
UNDERSTANDING_MODEL=deepseek-v4-flash
UNDERSTANDING_TEMPERATURE=0.0
UNDERSTANDING_TIMEOUT_SECONDS=10
UNDERSTANDING_CONFIDENCE_THRESHOLD=0.65

CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

语义理解支持三种模式：

- `keyword`：只使用原关键词分类器，适合离线开发。
- `llm`：只使用LLM；模型失败时返回未知意图并要求用户澄清。
- `hybrid`：LLM优先，超时、输出格式错误或没有真实Key时使用关键词兜底。

推荐使用`hybrid`。没有真实Key时，意图识别和回答都会走本地兜底，方便联调数据流程。

## 接口

- `GET /api/health`：检查模型、会话存储和长期存储状态。
- `POST /api/chat`：兼容接口，一次性返回完整回答。
- `POST /api/chat/stream`：SSE流式聊天，发送`delta`文本增量，完成后发送`done`元数据。
- `POST /api/feedback`：保存有帮助或没帮助评价。
- `GET /api/conversations`：查询当前测试用户的历史对话。
- `GET /api/conversations/{conversation_id}/messages`：查询指定对话消息。

聊天响应会返回：

```json
{
  "answer": "好的，我已为您记录转人工诉求。",
  "session_id": "会话状态ID",
  "conversation_id": "长期对话ID",
  "message_id": "AI回答消息ID",
  "ticket_id": "触发转人工时的工单ID",
  "provider": "local-fallback",
  "suggestions": []
}
```

## 订单查询Mock Tool

订单查询已经完成Python端闭环，目前不连接Java，测试数据位于`app/tools/order_tool.py`：

| Mock订单号 | 订单状态 |
| --- | --- |
| `ORDER_123456` | 已发货，预计明天送达 |
| `SHOP_778899` | 已签收 |
| `ORD_20260803_01` | 已付款，等待发货 |

对话流程为“识别订单查询 -> 缺少订单号时追问 -> 调用Mock Tool -> 直接返回完整话术”。其他订单号会返回未查询到的核对提示，不会调用回答LLM。

## 测试

```powershell
cd backend
uv run pytest
```

内存测试不连接Redis或PostgreSQL。外部服务安装完成后，还需要补一组真实Redis和PostgreSQL集成测试。
### 真实模型冒烟测试

真实模型测试默认跳过，避免普通测试意外产生模型费用。Windows PowerShell执行：

```powershell
cd backend
$env:RUN_LIVE_LLM_TESTS="1"
uv run pytest tests/test_understanding_live.py -v -s
```

Linux执行：

```bash
cd backend
RUN_LIVE_LLM_TESTS=1 uv run pytest tests/test_understanding_live.py -v -s
```

该测试只覆盖少量固定的联调场景，不属于批量评测集。
流式接口使用标准SSE格式：

```text
event: delta
data: {"content":"本次新增文本"}

event: done
data: {"answer":"完整回答","session_id":"...","message_id":"..."}
```

`done`事件发出前，完整回答已经写入配置的PostgreSQL或内存仓储。
## 意图检测评测

数据位于`evaluation/intent_cases.yaml`，包含8个已配置意图和unknown，共9类、每类25条。说法按真实客服口语风格整理，但不包含真实用户隐私。当前只评测语义理解，不进入编排器，也不会实际调用Tool。

另外提供`evaluation/intent_hard_cases.yaml`，包含90条独立难例，覆盖多意图、相似意图、否定表达、错别字、短句和多轮上下文。多意图主意图优先级统一配置在`app/configs/intents.yaml`：

```text
敏感风险 > 转人工 > 投诉 > 退款 > 奖励未到账 > 订单 > 权益 > 积分 > 活动规则
```

敏感风险由规则引擎直接转人工；普通意图顺序只在用户确实同时提出多个诉求时使用。

Windows PowerShell和Linux均可在`backend`目录执行：

```text
uv run python scripts/evaluate_intents.py --mode hybrid --concurrency 4
```

报告会写入`evaluation/reports`，包含意图准确率、槽位准确率、未知问题召回率、潜在错误Tool路由、LLM降级率和识别耗时。

执行难例集并自动检查生产门槛：

```text
uv run python scripts/evaluate_intents.py --dataset evaluation/intent_hard_cases.yaml --mode hybrid --concurrency 2 --check-thresholds
```

门槛位于难例集的`acceptance_thresholds`配置中。任何一项未通过时仍会生成报告，但命令返回退出码`2`，可以直接接入GitHub Actions或其他CI流程。

## Redis Search知识库与LangCache

当前语义层使用同一个Redis实例中的三个隔离索引：

- idx:cs:knowledge：25条人工确认的模拟知识，覆盖FAQ、活动规则、会员权益、退款规则和订单说明。
- idx:cs:langcache：保存达到频次门槛的模型答案，状态为unreviewed并设置短TTL。
- idx:cs:langcache-gap：对知识未命中问题做语义聚类，并按不同会话去重计数。

动态订单、积分、奖励等问题始终优先调用Tool；投诉、转人工、敏感问题和降级回答不会写入LangCache。

知识内容由Java管理后台写入PostgreSQL。审批通过后，Java Outbox可靠调用Python内部接口；Python完成切片、Embedding和Redis Search发布。旧YAML和手工发布脚本已经移除。

验证完整聊天命中：

    uv run python scripts/verify_chat_api.py

验证新增、审批、发布和停用闭环（脚本会自动清理测试数据）：

    uv run python scripts/verify_knowledge_admin.py

验证知识相近问法、负样本和LangCache高频闭环：

    uv run python scripts/verify_semantic_search.py

根据当前Embedding模型实测，知识库余弦距离门槛为0.38，LangCache门槛为0.20。更换模型或真实知识后必须重新评测并调整，不能直接沿用。

## Python每日问题学习任务

问题学习不经过Java。Python每天03:00直接从PostgreSQL领取“没帮助、差评、申请人工、
投诉、Tool失败、RAG无命中”信号，生成Embedding并使用pgvector聚类和统计次数。

```text
LEARNING_ENABLED=true
LEARNING_SCHEDULER_ENABLED=true
LEARNING_SCHEDULE_TIMEZONE=Asia/Shanghai
LEARNING_SCHEDULE_HOUR=3
LEARNING_SCHEDULE_MINUTE=0
  LEARNING_MAX_BATCHES=100
  LEARNING_BATCH_SIZE=100
  LEARNING_REVIEW_OCCURRENCE_THRESHOLD=3
  LEARNING_REVIEW_USER_THRESHOLD=2
  ```

  聚类统计完成后，普通问题满足“发生次数达到3次”或“受影响用户达到2人”任一条件，
  就会从`收集中`进入`待审核`；投诉属于高风险信号，单条直接进入待审核。
  Java后台提供真实问题列表、样本详情、标准回答保存、通过、驳回和忽略接口，
  所有生成和审核动作写入`learning.learning_problem_review`审计表。

  问题审核页的“LLM生成回答”调用Python，只生成可编辑草稿；前端随后调用Java保存，
  人工点击审核通过前不会自动发布到知识库。新提示词已加入本地兜底模板；需要同步到
  Nacos Prompt Registry时，在`backend`目录为其发布一个尚未使用的新版本：

  ```text
  uv run python scripts/publish_nacos_prompts.py --version 1.1.0 --label stable
  ```

  问题审核通过后的知识学习链路：

  ```text
  问题审核通过
      -> Python LLM生成知识标题、标签、3条标准问法和3至10条回归问法
      -> 人工选择知识分类并检查问法
      -> Java事务创建知识、版本、分片、标准问法、审批单和待审批测试集
      -> 知识审批通过：Outbox发布Redis Search，测试集同步生效
      -> 知识审批驳回/撤销：测试集标记驳回，来源问题恢复为已通过
  ```

  知识正文和测试用例的预期答案始终取自人工审核通过的标准回答，LLM不能在转换阶段
  改写业务事实。Flyway V12创建`learning.learning_evaluation_case`并保存问题、知识版本、
  生成模型和审批状态关联；后台“评测中心”通过Java接口读取这些真实用例。

部署多个Python实例时，每个实例都会计算调度时间，但执行前必须获得同一个PostgreSQL
advisory lock，因此只有一个实例真正处理。进程或数据库连接异常断开时锁会自动释放。

需要手动验证时，在`backend`目录执行：

```text
uv run python scripts/run_learning_job.py
```

健康检查`GET /api/health`会返回`learning_scheduler`和`learning_next_run`。

接入后的独立意图回归集位于evaluation/intent_cache_regression.yaml，只调用语义理解模型：

    uv run python scripts/evaluate_intents.py --dataset evaluation/intent_cache_regression.yaml --mode hybrid --concurrency 2
