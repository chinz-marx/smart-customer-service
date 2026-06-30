# 智能客服 Python 后端

基于 FastAPI + LangChain 1.x + 豆包大模型的客服回复服务，使用 uv 管理依赖，支持 Windows、Linux、macOS。

## 目录

```text
backend/
  app/
    main.py
    config.py
    customer_service.py
    schemas.py
  .env
  .python-version
  pyproject.toml
  uv.lock
  requirements.txt
```

## 配置

复制或修改 `.env`：

```env
DOUBAO_API_KEY=你的豆包API Key
DOUBAO_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
DOUBAO_MODEL=你的豆包模型名或 endpoint id
DOUBAO_TEMPERATURE=0.3
CORS_ORIGINS=http://localhost:5173,http://127.0.0.1:5173
```

如果 `DOUBAO_API_KEY` 仍是默认占位值，接口会使用本地兜底回复，方便前端先联调。

## 安装依赖

推荐使用 Python 3.12：

```bash
cd backend
uv sync --python 3.12
```

如果当前机器已经有可用的 Python 3.12，也可以直接运行：

```bash
cd backend
uv sync
```

## Linux/macOS 启动

```bash
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Windows PowerShell 启动

```powershell
cd backend
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

`requirements.txt` 仅保留给不使用 uv 的环境兼容；日常开发请以 `pyproject.toml` 和 `uv.lock` 为准。

## 接口

- `GET /api/health`
- `POST /api/chat`

请求示例：

```json
{
  "message": "我的奖励为什么还没到账?",
  "session_id": null,
  "history": []
}
```
