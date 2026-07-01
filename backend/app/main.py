from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import Settings, get_settings
from app.customer_service import CustomerServiceAgent
from app.schemas import ChatRequest, ChatResponse


def create_app() -> FastAPI:
    """创建 FastAPI 应用并注册路由。"""
    settings = get_settings()
    app = FastAPI(title=settings.app_name)

    # 前端 Vite 开发服务会从 5173 端口请求后端，所以这里开启 CORS。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health() -> dict[str, str]:
        """健康检查，同时告诉前端当前使用真实模型还是本地兜底。"""
        provider = "doubao" if settings.has_real_api_key else "local-fallback"
        return {"status": "ok", "provider": provider}

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(
        payload: ChatRequest,
        current_settings: Settings = Depends(get_settings),
    ) -> ChatResponse:
        """智能客服聊天入口。

        路由层只负责 HTTP 入参和最后兜底；正常业务错误在 orchestrator 内部降级处理。
        """
        try:
            agent = CustomerServiceAgent(current_settings)
            answer, session_id, provider, suggestions = await agent.reply(
                message=payload.message,
                session_id=payload.session_id,
                history=payload.history,
            )
            return ChatResponse(
                answer=answer,
                session_id=session_id,
                provider=provider,
                suggestions=suggestions,
            )
        except Exception:
            # 极端情况下仍然不把 Python 异常暴露给用户，返回可理解的客服兜底话术。
            return ChatResponse(
                answer="抱歉，客服服务暂时繁忙。我已记录您的问题，建议稍后再试或联系人工客服。",
                session_id=payload.session_id or "fallback-session",
                provider="system-fallback",
                suggestions=["联系人工客服", "重新描述问题", "稍后再试"],
            )

    return app


# Uvicorn 默认读取这个 app 变量：uvicorn app.main:app
app = create_app()