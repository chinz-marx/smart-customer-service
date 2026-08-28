from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.chat_service import ChatApplicationService
from app.config import Settings, get_settings
from app.infrastructure import create_chat_repository, create_learning_repository, create_session_store
from app.learning.scheduler import LearningDailyScheduler
from app.learning.service import LearningSignalProcessor
from app.learning.answer_generator import create_learning_answer_router
from app.learning.package_generator import create_learning_package_router
from app.evaluation.release_gate import create_release_evaluation_router
from app.evaluation.offline_benchmark import create_offline_benchmark_router
from app.integrations.nacos import NacosClient
from app.prompts.registry import PromptRegistry
from app.retrieval.chunk_splitter import create_knowledge_chunk_router
from app.retrieval.knowledge_publisher import (
    RedisKnowledgePublisher,
    create_knowledge_router,
)
from app.retrieval.question_generator import create_question_generation_router
from app.retrieval.service import create_semantic_answer_service
from app.schemas import (
    ChatRequest,
    ChatResponse,
    ConversationSummaryResponse,
    FeedbackRequest,
    FeedbackResponse,
    MessageResponse,
)
from app.tools.mcp_client import McpToolClient


logger = logging.getLogger("smart_customer_service.api")


def create_app(settings_override: Settings | None = None) -> FastAPI:
    """创建FastAPI应用，并在生命周期中管理Redis和数据库连接。"""
    settings = settings_override or get_settings()
    # 路由中的标准问法生成器和聊天编排共享同一个内存提示词注册表。
    prompt_registry = PromptRegistry(settings, None)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        """启动时连接存储，关闭时释放连接池。"""
        session_store = create_session_store(settings)
        repository = create_chat_repository(settings)
        learning_repository = create_learning_repository(settings)
        semantic_answer_service = create_semantic_answer_service(settings)
        knowledge_publisher = (
            RedisKnowledgePublisher(settings) if settings.semantic_search_enabled else None
        )
        nacos_client = NacosClient(settings) if settings.nacos_enabled else None
        prompt_registry.nacos_client = nacos_client
        await prompt_registry.initialize()
        mcp_tool_client = McpToolClient(settings, nacos_client)
        await mcp_tool_client.initialize()
        learning_processor: LearningSignalProcessor | None = None
        learning_scheduler: LearningDailyScheduler | None = None
        try:
            # 所有需要建立网络连接的组件都放在同一个保护区内。这样 Redis 初始化失败时，
            # 已经建立的 MCP、Nacos 和 HTTP 连接也能被下面的清理逻辑可靠释放。
            await session_store.initialize()
            await repository.initialize()
            await learning_repository.initialize()
            await semantic_answer_service.initialize()
            if knowledge_publisher is not None:
                await knowledge_publisher.initialize()
            if settings.learning_enabled:
                learning_processor = LearningSignalProcessor(settings, learning_repository)
            if learning_processor is not None and settings.learning_scheduler_enabled:
                learning_scheduler = LearningDailyScheduler(
                    settings, learning_repository, learning_processor
                )
                learning_scheduler.start()
        except Exception:
            if learning_scheduler is not None:
                await learning_scheduler.close()
            if learning_processor is not None:
                await learning_processor.close()
            if knowledge_publisher is not None:
                await knowledge_publisher.close()
            await semantic_answer_service.close()
            await repository.close()
            await learning_repository.close()
            await session_store.close()
            await mcp_tool_client.close()
            if nacos_client is not None:
                await nacos_client.close()
            raise

        app.state.session_store = session_store
        app.state.chat_repository = repository
        app.state.learning_repository = learning_repository
        app.state.learning_processor = learning_processor
        app.state.learning_scheduler = learning_scheduler
        app.state.semantic_answer_service = semantic_answer_service
        app.state.knowledge_publisher = knowledge_publisher
        app.state.prompt_registry = prompt_registry
        app.state.mcp_tool_client = mcp_tool_client
        app.state.chat_service = ChatApplicationService(
            settings,
            session_store,
            repository,
            semantic_answer_service,
            prompt_registry,
            mcp_tool_client,
            learning_repository,
        )
        try:
            yield
        finally:
            if learning_scheduler is not None:
                await learning_scheduler.close()
            if learning_processor is not None:
                await learning_processor.close()
            if knowledge_publisher is not None:
                await knowledge_publisher.close()
            await semantic_answer_service.close()
            await repository.close()
            await learning_repository.close()
            await session_store.close()
            await mcp_tool_client.close()
            if nacos_client is not None:
                await nacos_client.close()

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.include_router(create_knowledge_chunk_router())
    app.include_router(create_knowledge_router(settings))
    app.include_router(create_question_generation_router(settings, prompt_registry))
    app.include_router(create_learning_answer_router(settings, prompt_registry))
    app.include_router(create_learning_package_router(settings, prompt_registry))
    app.include_router(create_release_evaluation_router(settings))
    app.include_router(create_offline_benchmark_router())

    # Vite开发服务会从5173端口请求后端，所以这里开启CORS。
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/api/health")
    async def health(request: Request) -> dict[str, str]:
        """检查模型模式、Redis会话和长期持久化是否可用。"""
        provider = "doubao" if settings.has_real_api_key else "local-fallback"
        understanding_provider = (
            "deepseek" if settings.has_real_understanding_api_key else "keyword"
        )
        session_ok = await request.app.state.session_store.health_check()
        database_ok = await request.app.state.chat_repository.health_check()
        semantic_ok = await request.app.state.semantic_answer_service.health_check()
        mcp_client: McpToolClient = request.app.state.mcp_tool_client
        mcp_ok = not settings.mcp_enabled or bool(mcp_client.catalog())
        learning_scheduler: LearningDailyScheduler | None = (
            request.app.state.learning_scheduler
        )
        return {
            "status": (
                "ok"
                if session_ok and database_ok and semantic_ok and mcp_ok
                else "degraded"
            ),
            "provider": provider,
            "understanding_provider": understanding_provider,
            "session_store": settings.session_store_backend,
            "session_store_status": "ok" if session_ok else "error",
            "persistence": settings.persistence_backend,
            "persistence_status": "ok" if database_ok else "error",
            "semantic_search": "enabled" if settings.semantic_search_enabled else "disabled",
            "semantic_search_status": "ok" if semantic_ok else "error",
            "prompt_source": request.app.state.prompt_registry.source,
            "mcp": "enabled" if settings.mcp_enabled else "disabled",
            "mcp_status": "ok" if mcp_ok else "error",
            "mcp_tools": ",".join(tool["name"] for tool in mcp_client.catalog()),
            "mcp_tool_retrieval": mcp_client.tool_retrieval_status,
            "learning_scheduler": "enabled" if learning_scheduler else "disabled",
            "learning_next_run": (
                learning_scheduler.next_run_time().isoformat()
                if learning_scheduler is not None
                else ""
            ),
        }

    @app.post("/api/chat", response_model=ChatResponse)
    async def chat(payload: ChatRequest, request: Request) -> ChatResponse:
        """聊天入口，同时完成消息持久化和自动工单创建。"""
        service: ChatApplicationService = request.app.state.chat_service
        try:
            return await service.chat(payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception:
            # 日志保留堆栈供开发排查，但响应不暴露数据库或模型异常细节。
            logger.exception("聊天请求处理失败")
            return ChatResponse(
                answer="抱歉，客服服务暂时繁忙。建议稍后再试或联系人工客服。",
                session_id=payload.session_id or str(uuid.uuid4()),
                conversation_id=payload.conversation_id,
                provider="system-fallback",
                suggestions=["联系人工客服", "重新描述问题", "稍后再试"],
            )

    @app.post("/api/chat/stream")
    async def chat_stream(payload: ChatRequest, request: Request) -> StreamingResponse:
        """使用SSE逐块返回回答；POST请求体与普通聊天接口保持一致。"""
        service: ChatApplicationService = request.app.state.chat_service
        return StreamingResponse(
            service.chat_stream(payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/feedback", response_model=FeedbackResponse)
    async def save_feedback(payload: FeedbackRequest, request: Request) -> FeedbackResponse:
        """保存用户针对某条AI回答的有用或无用评价。"""
        service: ChatApplicationService = request.app.state.chat_service
        try:
            record = await service.save_feedback(payload)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return FeedbackResponse(
            feedback_id=record.id,
            feedback_type=record.feedback_type,
            updated_at=record.updated_at,
        )

    @app.get("/api/conversations", response_model=list[ConversationSummaryResponse])
    async def list_conversations(
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[ConversationSummaryResponse]:
        """返回当前测试用户最近的历史对话。"""
        service: ChatApplicationService = request.app.state.chat_service
        records = await service.list_conversations(limit=limit)
        return [
            ConversationSummaryResponse(
                id=record.id,
                session_id=record.session_id,
                title=record.title,
                status=record.status,
                channel=record.channel,
                created_at=record.created_at,
                updated_at=record.updated_at,
            )
            for record in records
        ]

    @app.get("/api/conversations/{conversation_id}/messages", response_model=list[MessageResponse])
    async def list_messages(
        conversation_id: str,
        request: Request,
        limit: int = Query(default=100, ge=1, le=200),
    ) -> list[MessageResponse]:
        """返回指定对话的历史消息。"""
        service: ChatApplicationService = request.app.state.chat_service
        try:
            records = await service.list_messages(conversation_id, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return [
            MessageResponse(
                id=record.id,
                conversation_id=record.conversation_id,
                role=record.role,
                content=record.content,
                intent=record.intent,
                provider=record.provider,
                created_at=record.created_at,
            )
            for record in records
        ]

    return app


# Uvicorn默认读取这个变量：uvicorn app.main:app
app = create_app()


if __name__ == "__main__":
    # 直接执行python -m app.main时，端口等参数统一读取.env。
    import uvicorn

    runtime_settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=runtime_settings.app_host,
        port=runtime_settings.app_port,
        reload=runtime_settings.app_reload,
    )
