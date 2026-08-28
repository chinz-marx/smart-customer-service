from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    select,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.persistence.domain import (
    ConversationRecord,
    FeedbackRecord,
    MessageRecord,
    TicketRecord,
    utc_now,
)


class Base(DeclarativeBase):
    """所有SQLAlchemy数据模型的基类。"""


class ConversationModel(Base):
    """客服会话表。"""

    __tablename__ = "chat_conversation"
    __table_args__ = (
        UniqueConstraint("user_id", "session_id", name="uq_conversation_user_session"),
        Index("ix_conversation_user_updated", "user_id", "updated_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    session_id: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    channel: Mapped[str] = mapped_column(String(20), nullable=False, default="web")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class MessageModel(Base):
    """聊天消息表。"""

    __tablename__ = "chat_message"
    __table_args__ = (
        UniqueConstraint("request_id", name="uq_message_request_id"),
        Index("ix_message_conversation_created", "conversation_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str] = mapped_column(String(64), nullable=False)
    intent: Mapped[str | None] = mapped_column(String(64))
    intent_confidence: Mapped[float | None] = mapped_column(Float)
    provider: Mapped[str | None] = mapped_column(String(40))
    latency_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)


class FeedbackModel(Base):
    """用户反馈表。"""

    __tablename__ = "chat_feedback"
    __table_args__ = (
        UniqueConstraint("user_id", "message_id", name="uq_feedback_user_message"),
        Index("ix_feedback_type_created", "feedback_type", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    message_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_message.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    feedback_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rating: Mapped[int | None] = mapped_column(Integer)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class TicketModel(Base):
    """人工客服工单表。"""

    __tablename__ = "service_ticket"
    __table_args__ = (
        Index("ix_ticket_status_created", "status", "created_at"),
        Index("ix_ticket_conversation", "conversation_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("chat_conversation.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str] = mapped_column(String(120), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    context_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    priority: Mapped[str] = mapped_column(String(20), nullable=False, default="normal")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    assigned_agent_id: Mapped[str | None] = mapped_column(String(64))
    external_ticket_id: Mapped[str | None] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class PostgresChatRepository:
    """SQLAlchemy 2.x异步PostgreSQL仓储实现。

    PostgreSQL 18可以直接使用这些DDL；JSON上下文使用原生JSONB字段。
    """

    def __init__(self, database_url: str, echo: bool = False, auto_create_tables: bool = False) -> None:
        self.engine: AsyncEngine = create_async_engine(
            database_url,
            echo=echo,
            pool_pre_ping=True,
        )
        self.session_factory = async_sessionmaker(self.engine, expire_on_commit=False)
        self.auto_create_tables = auto_create_tables

    async def initialize(self) -> None:
        """检查数据库连接；开发模式可自动创建表。"""
        async with self.engine.begin() as connection:
            if self.auto_create_tables:
                await connection.run_sync(Base.metadata.create_all)
            else:
                await connection.execute(text("SELECT 1"))

    async def get_or_create_conversation(
        self,
        user_id: str,
        session_id: str,
        conversation_id: str | None,
        title: str,
    ) -> ConversationRecord:
        """查询或创建当前用户的会话。"""
        import uuid

        async with self.session_factory() as session:
            if conversation_id:
                statement = select(ConversationModel).where(
                    ConversationModel.id == conversation_id,
                    ConversationModel.user_id == user_id,
                )
            else:
                statement = select(ConversationModel).where(
                    ConversationModel.session_id == session_id,
                    ConversationModel.user_id == user_id,
                )
            model = await session.scalar(statement)
            if model is not None:
                return _conversation_record(model)
            if conversation_id:
                raise ValueError("对话不存在或不属于当前用户")

            model = ConversationModel(
                id=str(uuid.uuid4()),
                user_id=user_id,
                session_id=session_id,
                title=title[:120],
                status="active",
                channel="web",
            )
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _conversation_record(model)

    async def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        request_id: str,
        intent: str | None = None,
        intent_confidence: float | None = None,
        provider: str | None = None,
        latency_ms: float | None = None,
    ) -> MessageRecord:
        """在一个事务中保存消息并刷新会话更新时间。"""
        import uuid

        async with self.session_factory() as session:
            conversation = await session.get(ConversationModel, conversation_id)
            if conversation is None:
                raise ValueError("对话不存在")
            model = MessageModel(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                role=role,
                content=content,
                request_id=request_id,
                intent=intent,
                intent_confidence=intent_confidence,
                provider=provider,
                latency_ms=latency_ms,
            )
            conversation.updated_at = utc_now()
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _message_record(model)

    async def list_conversations(self, user_id: str, limit: int = 20) -> list[ConversationRecord]:
        """返回用户最近更新的对话。"""
        async with self.session_factory() as session:
            statement = (
                select(ConversationModel)
                .where(ConversationModel.user_id == user_id)
                .order_by(ConversationModel.updated_at.desc())
                .limit(limit)
            )
            rows = (await session.scalars(statement)).all()
            return [_conversation_record(row) for row in rows]

    async def list_messages(
        self,
        conversation_id: str,
        user_id: str,
        limit: int = 100,
    ) -> list[MessageRecord]:
        """校验会话归属后返回最近消息，并保持时间正序。"""
        async with self.session_factory() as session:
            owner_statement = select(ConversationModel.id).where(
                ConversationModel.id == conversation_id,
                ConversationModel.user_id == user_id,
            )
            if await session.scalar(owner_statement) is None:
                raise ValueError("对话不存在或不属于当前用户")
            statement = (
                select(MessageModel)
                .where(MessageModel.conversation_id == conversation_id)
                .order_by(MessageModel.created_at.desc())
                .limit(limit)
            )
            rows = list((await session.scalars(statement)).all())
            rows.reverse()
            return [_message_record(row) for row in rows]

    async def save_feedback(
        self,
        conversation_id: str,
        message_id: str,
        user_id: str,
        feedback_type: str,
        rating: int | None,
        comment: str | None,
    ) -> FeedbackRecord:
        """保存反馈；同一用户重复评价同一回答时执行更新。"""
        import uuid

        async with self.session_factory() as session:
            message_statement = (
                select(MessageModel)
                .join(ConversationModel, ConversationModel.id == MessageModel.conversation_id)
                .where(
                    MessageModel.id == message_id,
                    MessageModel.conversation_id == conversation_id,
                    MessageModel.role == "assistant",
                    ConversationModel.user_id == user_id,
                )
            )
            if await session.scalar(message_statement) is None:
                raise ValueError("只能评价当前用户对话中的AI回答")

            statement = select(FeedbackModel).where(
                FeedbackModel.message_id == message_id,
                FeedbackModel.user_id == user_id,
            )
            model = await session.scalar(statement)
            if model is None:
                model = FeedbackModel(
                    id=str(uuid.uuid4()),
                    conversation_id=conversation_id,
                    message_id=message_id,
                    user_id=user_id,
                    feedback_type=feedback_type,
                    rating=rating,
                    comment=comment,
                )
                session.add(model)
            else:
                model.feedback_type = feedback_type
                model.rating = rating
                model.comment = comment
                model.updated_at = utc_now()
            await session.commit()
            await session.refresh(model)
            return _feedback_record(model)

    async def create_ticket(
        self,
        conversation_id: str,
        user_id: str,
        reason: str,
        summary: str,
        context_snapshot: dict[str, object],
        priority: str = "normal",
    ) -> TicketRecord:
        """创建人工工单，并避免同一对话重复产生未完成工单。"""
        import uuid

        async with self.session_factory() as session:
            conversation_statement = select(ConversationModel).where(
                ConversationModel.id == conversation_id,
                ConversationModel.user_id == user_id,
            )
            conversation = await session.scalar(conversation_statement)
            if conversation is None:
                raise ValueError("对话不存在或不属于当前用户")

            open_ticket_statement = select(TicketModel).where(
                TicketModel.conversation_id == conversation_id,
                TicketModel.status.in_(["pending", "processing"]),
            )
            existing = await session.scalar(open_ticket_statement)
            if existing is not None:
                return _ticket_record(existing)

            model = TicketModel(
                id=str(uuid.uuid4()),
                conversation_id=conversation_id,
                user_id=user_id,
                reason=reason,
                summary=summary,
                context_snapshot=context_snapshot,
                priority=priority,
                status="pending",
            )
            conversation.status = "handoff"
            conversation.updated_at = utc_now()
            session.add(model)
            await session.commit()
            await session.refresh(model)
            return _ticket_record(model)

    async def health_check(self) -> bool:
        """执行轻量SQL检查数据库连接。"""
        try:
            async with self.engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
            return True
        except Exception:
            return False

    async def close(self) -> None:
        """释放SQLAlchemy连接池。"""
        await self.engine.dispose()


def _conversation_record(model: ConversationModel) -> ConversationRecord:
    return ConversationRecord(
        id=model.id,
        user_id=model.user_id,
        session_id=model.session_id,
        title=model.title,
        status=model.status,
        channel=model.channel,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _message_record(model: MessageModel) -> MessageRecord:
    return MessageRecord(
        id=model.id,
        conversation_id=model.conversation_id,
        role=model.role,
        content=model.content,
        request_id=model.request_id,
        intent=model.intent,
        intent_confidence=model.intent_confidence,
        provider=model.provider,
        latency_ms=model.latency_ms,
        created_at=model.created_at,
    )


def _feedback_record(model: FeedbackModel) -> FeedbackRecord:
    return FeedbackRecord(
        id=model.id,
        conversation_id=model.conversation_id,
        message_id=model.message_id,
        user_id=model.user_id,
        feedback_type=model.feedback_type,
        rating=model.rating,
        comment=model.comment,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )


def _ticket_record(model: TicketModel) -> TicketRecord:
    return TicketRecord(
        id=model.id,
        conversation_id=model.conversation_id,
        user_id=model.user_id,
        reason=model.reason,
        summary=model.summary,
        context_snapshot=model.context_snapshot,
        priority=model.priority,
        status=model.status,
        assigned_agent_id=model.assigned_agent_id,
        external_ticket_id=model.external_ticket_id,
        created_at=model.created_at,
        updated_at=model.updated_at,
    )