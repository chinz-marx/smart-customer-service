# 智能客服 Python 服务

Python 3.12 + FastAPI 服务。它负责客服消息的 SSE 输出、会话状态、上下文解析、知识检索、MCP 编排、学习信号和离线评测；确定性业务数据由 Java MCP 服务提供。

## 运行边界

- 模型只解释当前用户消息，不生成会话状态或业务执行计划。
- `DialogueManager` 维护多轮任务、缺失参数、确认、纠正和插话恢复。
- PostgreSQL 保存会话、消息、反馈、工单和学习数据；Redis 保存可重建的状态、回执、锁和检索索引。
- `sessionId`、`userId`、`requestId` 在调用 MCP 前由代码注入，不能由用户消息或模型提供。
- 工具结果和已发布原子知识可直接返回；知识未命中或工具只返回原始数据时，回答模型负责组织回复。

完整的上下文协议、状态机和一致性约束见 [DIALOGUE.md](./DIALOGUE.md)。

## 环境要求

- Python `>=3.12,<3.13`
- [uv](https://docs.astral.sh/uv/)
- 可选：PostgreSQL、Redis Stack、Nacos、OpenAI 兼容模型服务和 Java MCP 服务

```powershell
cd backend
uv sync --python 3.12
Copy-Item .env.example .env
```

`.env` 只保留本地或部署环境，不可提交。示例文件列出了全部可用配置项。

## 启动

```powershell
cd backend
uv run python -m app.main
```

默认监听 `0.0.0.0:8000`。本地可使用 `APP_RELOAD=true`，生产环境应关闭自动重载。

```text
GET  /api/health
POST /api/chat
POST /api/chat/stream
POST /api/feedback
GET  /api/conversations
GET  /api/conversations/{conversation_id}/messages
```

`/api/chat/stream` 使用 SSE：

```text
event: delta
data: {"content":"本次新增文本"}

event: done
data: {"answer":"完整回答","session_id":"...","conversation_id":"...","provider":"..."}
```

首个回答片段可以在消息持久化完成前发出；用户消息、助手消息和学习信号会由受管理后台任务按顺序保存。服务停止时会等待已接受的后台任务完成。

## 关键配置

| 配置组 | 用途 |
| --- | --- |
| `UNDERSTANDING_*` | 上下文解析模型。`hybrid` 表示模型失败后使用关键词降级。 |
| `DOUBAO_*` | 回答、标准问法和 Embedding 模型。 |
| `SESSION_STORE_BACKEND` | `memory` 或 `redis`。Redis 模式支持分布式锁和请求回执。 |
| `PERSISTENCE_BACKEND` | `memory` 或 `postgres`。 |
| `SEMANTIC_SEARCH_ENABLED` | Redis Search 知识库与 LangCache。 |
| `MCP_ENABLED` | Java MCP Streamable HTTP 客户端。 |
| `NACOS_ENABLED` | 提示词、本地路由配置和 MCP 地址发现。 |
| `CONTEXT_CANDIDATE_TIMEOUT_SECONDS` | 候选 Tool 召回预算，默认 0.5 秒。 |

Nacos 读取失败时，提示词、本地路由配置和 MCP 地址均有本地回退。Nacos 只在启动和配置轮询中使用，不会进入每轮聊天的关键链路。

## 知识服务

知识由 Java 后台管理，并通过 Outbox 调用 Python 内部接口：

| 接口 | 用途 |
| --- | --- |
| `POST /api/knowledge/chunks/split` | 将正文拆分为原子切片 |
| `POST /api/knowledge/questions/generate` | 为切片生成标准问法 |
| `POST /api/internal/knowledge/publish` | 生成向量并发布至 Redis Search |
| `POST /api/internal/knowledge/delete` | 删除已停用版本的索引 |

标准问法和知识切片都写入 `idx:cs:knowledge`。知识余弦距离不超过 `0.38` 时命中；命中后直接返回已发布切片，因此线上知识必须能够独立回答一个用户问题。LangCache 只在知识未命中后查询。

## 实时语音输入

聊天页的“语音输入”“点击说话”和左侧“语音助手”使用同一条实时识别链路。
点击开始后边说边显示文字；点击结束后等待最终结果，可编辑并点击发送。
录音过程中禁止发送半成品，取消会恢复录音前的输入。单次默认最多60秒。

```text
AudioWorklet → 16kHz/单声道/PCM S16LE → WebSocket /api/speech/stream
             → Python → 豆包 bigmodel_async → partial/final → 输入框
             → 用户确认发送 → POST /api/chat/stream → SSE回答
```

在 `backend/.env` 中配置 `ASR_API_KEY`，使用豆包语音新控制台的 API Key，
通过 `X-Api-Key` 鉴权。默认 Resource ID 为 `volc.seedasr.sauc.duration`，
地址为 `wss://openspeech.bytedance.com/api/v3/sauc/bigmodel_async`。
后端为每次录音生成独立 UUID 作为供应商请求 ID。该凭证与方舟聊天模型的 Key 独立，
禁止使用 `VITE_` 变量将其打包到浏览器。

前端真实重采样到16kHz，每100ms发送3200字节二进制音频，发送与识别接收并发进行。
结束时先清空最后一包音频，再发送结束标记并等待最终响应。识别结果为全文快照，
更新当前录音文本而非重复追加。Python在内存中转发，不保存音频或识别文本；
用户发送后才通过既有聊天流程保存文字。日志只包含请求ID、音频长度和耗时。

WebSocket控制消息：开始为
`{"type":"start","format":"pcm_s16le","sample_rate":16000,"channels":1}`，
随后发送二进制PCM；停止为 `{"type":"finish"}`，取消为 `{"type":"cancel"}`。
返回消息类型为 `ready`、`partial`、`final`、`error`。

部署需要HTTPS（本机开发可用localhost/127.0.0.1）以及反向代理的WebSocket Upgrade支持。
Vite已开启 `/api` 的WebSocket代理。跨域部署时在 `CORS_ORIGINS` 中明确加入网页来源，
WebSocket路由也会单独校验Origin。`ASR_MAX_CONNECTIONS` 是单个Python进程的并发上限；
接入现有登录体系时还应增加用户维度额度，不应将Origin校验视为用户鉴权。

验证命令：

```powershell
# 在backend目录：不访问真实ASR的协议、取消、超时等测试
uv run pytest tests/test_speech.py -q -p no:cacheprovider
# 在frontend目录：重采样、文本修正、取消及资源清理测试
npm run test:speech
# 在backend目录：显式调用真实ASR，仅使用自行准备的16kHz单声道PCM16测试WAV
uv run python scripts/check_asr_stream.py --wav path/to/synthetic.wav --expect "订单"
# 可选通过正在运行的Vite代理验证完整链路
uv run python scripts/check_asr_stream.py --gateway ws://127.0.0.1:5173/api/speech/stream --wav path/to/synthetic.wav
```

## 聊天链路观测

`ChatTimingMiddleware` 为 `/api/chat` 和 `/api/chat/stream` 输出 `chat_timing` JSON 日志，覆盖：

- 会话锁、Redis 回执、状态读写；
- PostgreSQL 会话与消息读写；
- 上下文解析、Tool 候选和模型调用；
- 知识检索、MCP 调用、回答模型；
- 首字节、完成和总耗时。

嵌套 span 可能重叠，分析时不能直接相加。日志不记录用户完整对话内容。

## 测试

```powershell
cd backend
uv run pytest -q -p no:cacheprovider
```

真实模型和 Redis 集成测试默认跳过。需要时显式设置：

```powershell
$env:RUN_LIVE_LLM_TESTS = "1"
uv run pytest tests/test_context_live.py -q -s -p no:cacheprovider
Remove-Item Env:RUN_LIVE_LLM_TESTS
```

真实 Redis 状态机测试使用随机前缀，只清理自身创建的键：

```powershell
$env:RUN_DIALOGUE_REDIS_TESTS = "1"
uv run pytest tests/test_dialogue_redis.py -q -p no:cacheprovider
Remove-Item Env:RUN_DIALOGUE_REDIS_TESTS
```

## 目录

```text
backend/
├─ app/
│  ├─ dialogue/          上下文状态机
│  ├─ understanding/     四字段模型协议与路由转换
│  ├─ retrieval/         切片、问法、Embedding、发布与检索
│  ├─ tools/             MCP 客户端、Schema 校验和 Tool 召回
│  ├─ session/           Redis/内存状态、锁与回执
│  ├─ learning/          问题学习和知识包生成
│  ├─ observability/     请求链路计时
│  └─ persistence/       PostgreSQL 仓储
├─ scripts/              发布、评测和验证脚本
├─ tests/
├─ .env.example
├─ DIALOGUE.md
└─ pyproject.toml
```
