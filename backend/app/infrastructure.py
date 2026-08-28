from __future__ import annotations

from app.config import Settings
from app.learning.repository import (
    DisabledLearningRepository,
    InMemoryLearningRepository,
    LearningRepository,
    PostgresLearningRepository,
)
from app.persistence.repository import ChatRepository, InMemoryChatRepository
from app.session.store import InMemorySessionStore, RedisSessionStore, SessionStore


def create_session_store(settings: Settings) -> SessionStore:
    """按配置创建会话存储，默认内存，生产环境使用Redis。"""
    if settings.session_store_backend == "redis":
        return RedisSessionStore(
            redis_url=settings.redis_url,
            ttl_seconds=settings.redis_session_ttl_seconds,
            key_prefix=settings.redis_session_key_prefix,
        )
    return InMemorySessionStore()


def create_chat_repository(settings: Settings) -> ChatRepository:
    """按配置创建长期数据仓储，默认内存，生产环境使用PostgreSQL。"""
    if settings.persistence_backend == "postgres":
        # 延迟导入让未安装SQLAlchemy时仍可使用内存模式完成自测。
        from app.persistence.postgres import PostgresChatRepository

        return PostgresChatRepository(
            database_url=settings.database_url,
            echo=settings.database_echo,
            auto_create_tables=settings.database_auto_create_tables,
        )
    return InMemoryChatRepository()


def create_learning_repository(settings: Settings) -> LearningRepository:
    """创建独立的问题学习仓储，关闭时不增加数据库连接和外部调用。"""
    if not settings.learning_enabled:
        return DisabledLearningRepository()
    if settings.persistence_backend == "postgres":
        return PostgresLearningRepository(settings.database_url, settings.database_echo)
    return InMemoryLearningRepository()
