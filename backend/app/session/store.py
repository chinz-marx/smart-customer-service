from __future__ import annotations
from app.observability.timing import timed

import json
import hashlib
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app.slots.schemas import SlotValue
from app.dialogue.schemas import DialogueContext
from app.session.coordination import MemoryLocks, active_redis_lease, redis_session_lock


_FENCED_SET = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
return 1
"""


def bind_owner(state, conversation_id, user_id):
    if user_id is not None and state.user_id is not None and state.user_id != user_id:
        raise ValueError("会话不存在或不属于当前用户")
    if conversation_id and state.conversation_id and state.conversation_id != conversation_id:
        raise ValueError("会话与对话不匹配")
    state.user_id = state.user_id or user_id
    state.conversation_id = state.conversation_id or conversation_id


def receipt_key(session_id, user_id, request_id):
    return hashlib.sha256(json.dumps([session_id, user_id, request_id]).encode()).hexdigest()


def utc_now() -> datetime:
    """返回带时区的UTC时间，避免Windows和Linux使用不同的本地时区。"""
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class ConversationState:
    """单个会话在运行期间需要保存的短期状态。

    完整聊天记录保存在PostgreSQL；这里只保存意图、槽位等多轮编排状态。
    """

    session_id: str
    conversation_id: str | None = None
    user_id: str | None = None
    current_intent: str | None = None
    active_tool: str | None = None
    tool_status: str | None = None
    tool_arguments: dict[str, str] = field(default_factory=dict)
    last_tool: str | None = None
    dialogue: DialogueContext = field(default_factory=DialogueContext)
    slots: dict[str, SlotValue] = field(default_factory=dict)
    turn_count: int = 0
    updated_at: datetime = field(default_factory=utc_now)

    def touch(self) -> None:
        """每轮对话后刷新轮次和更新时间。"""
        self.turn_count += 1
        self.updated_at = utc_now()

    def to_dict(self) -> dict[str, Any]:
        """转换成可以安全写入Redis JSON字符串的字典。"""
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "user_id": self.user_id,
            "current_intent": self.current_intent,
            "active_tool": self.active_tool,
            "tool_status": self.tool_status,
            "tool_arguments": self.tool_arguments,
            "last_tool": self.last_tool,
            "dialogue": self.dialogue.model_dump(mode="json"),
            "slots": {
                code: {
                    "value": slot.value,
                    "confidence": slot.confidence,
                    "source_text": slot.source_text,
                    "validated": slot.validated,
                }
                for code, slot in self.slots.items()
            },
            "turn_count": self.turn_count,
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ConversationState":
        """把Redis中的字典恢复成会话状态对象。"""
        raw_slots = data.get("slots", {})
        slots = {
            code: SlotValue(
                value=str(slot_data.get("value", "")),
                confidence=float(slot_data.get("confidence", 0.0)),
                source_text=str(slot_data.get("source_text", "")),
                validated=bool(slot_data.get("validated", True)),
            )
            for code, slot_data in raw_slots.items()
            if isinstance(slot_data, dict)
        }
        raw_updated_at = data.get("updated_at")
        updated_at = datetime.fromisoformat(raw_updated_at) if raw_updated_at else utc_now()
        return cls(
            session_id=str(data["session_id"]),
            conversation_id=data.get("conversation_id"),
            user_id=data.get("user_id"),
            current_intent=data.get("current_intent"),
            active_tool=data.get("active_tool"),
            tool_status=data.get("tool_status"),
            tool_arguments={
                str(key): str(value)
                for key, value in data.get("tool_arguments", {}).items()
            },
            last_tool=data.get("last_tool"),
            dialogue=DialogueContext.model_validate(data.get("dialogue") or {}),
            slots=slots,
            turn_count=int(data.get("turn_count", 0)),
            updated_at=updated_at,
        )


class SessionStore(Protocol):
    """会话存储统一接口，内存和Redis实现都遵守这份契约。"""

    async def initialize(self) -> None:
        """初始化连接并尽早暴露配置错误。"""

    async def get_or_create(
        self,
        session_id: str,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> ConversationState:
        """读取已有状态，不存在时创建新状态。"""

    async def save(self, state: ConversationState) -> None:
        """保存状态并刷新过期时间。"""

    async def delete(self, session_id: str) -> None:
        """删除指定会话的短期状态。"""

    async def health_check(self) -> bool:
        """检查存储是否可用。"""

    async def close(self) -> None:
        """释放连接资源。"""

    def lock(self, session_id: str): ...

    async def get_receipt(self, key: str) -> dict | None: ...

    async def save_receipt(self, key: str, value: dict) -> None: ...


class InMemorySessionStore:
    """开发和单元测试使用的内存会话存储。"""

    def __init__(self, ttl_seconds: int = 1800) -> None:
        self._sessions: dict[str, ConversationState] = {}
        self.ttl_seconds = ttl_seconds
        self._locks = MemoryLocks()
        self._receipts: dict[str, tuple[float, dict]] = {}

    def lock(self, session_id: str):
        return self._locks.hold(session_id)

    async def get_receipt(self, key: str) -> dict | None:
        self._receipts = {k: v for k, v in self._receipts.items() if v[0] > time.time()}
        entry = self._receipts.get(key)
        return entry[1] if entry else None

    async def save_receipt(self, key: str, value: dict) -> None:
        self._receipts[key] = (time.time() + 86400, value)

    async def initialize(self) -> None:
        """内存实现不需要建立外部连接。"""

    async def get_or_create(
        self,
        session_id: str,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> ConversationState:
        """根据session_id获取已有会话，没有就创建。"""
        state = self._sessions.get(session_id)
        if state and (utc_now() - state.updated_at).total_seconds() >= self.ttl_seconds:
            self._sessions.pop(session_id, None)
            state = None
        if state is None:
            state = ConversationState(
                session_id=session_id,
                conversation_id=conversation_id,
                user_id=user_id,
            )
            self._sessions[session_id] = state
        else:
            # 老状态可能来自尚未持久化conversation_id的第一轮，这里补齐关联信息。
            bind_owner(state, conversation_id, user_id)
        return ConversationState.from_dict(state.to_dict())

    async def save(self, state: ConversationState) -> None:
        """保存会话状态。内存实现里就是覆盖字典。"""
        self._sessions[state.session_id] = ConversationState.from_dict(state.to_dict())

    async def delete(self, session_id: str) -> None:
        """删除会话；不存在时不报错。"""
        self._sessions.pop(session_id, None)

    async def health_check(self) -> bool:
        """进程存活时内存存储始终可用。"""
        return True

    async def close(self) -> None:
        """内存实现没有需要关闭的连接。"""


class RedisSessionStore:
    """使用redis-py异步客户端实现的Redis会话存储。

    Redis服务端按7.2设计，Key使用统一前缀，Value保存UTF-8 JSON，
    每次save都会刷新TTL，适合保存短期多轮对话状态。
    """

    def __init__(self, redis_url: str, ttl_seconds: int, key_prefix: str = "cs:session:") -> None:
        self.redis_url = redis_url
        self.ttl_seconds = ttl_seconds
        self.key_prefix = key_prefix
        self._client: Any | None = None

    def lock(self, session_id: str):
        return redis_session_lock(self, session_id)

    @timed("redis.receipt.read")
    async def get_receipt(self, key: str) -> dict | None:
        payload = await self._require_client().get(f"{self.key_prefix}request:{key}")
        return json.loads(payload) if payload else None

    @timed("redis.receipt.write")
    async def save_receipt(self, key: str, value: dict) -> None:
        await self._fenced_set(f"{self.key_prefix}request:{key}", json.dumps(value, ensure_ascii=False), 86400)

    async def _fenced_set(self, key: str, payload: str, ttl: int, session_id=None) -> None:
        lease = active_redis_lease(self, session_id)
        if lease is None:
            await self._require_client().set(key, payload, ex=ttl)
            return
        saved = await self._require_client().eval(
            _FENCED_SET, 2, lease.name, key, lease.local.token, payload, ttl,
        )
        if not saved:
            raise RuntimeError("会话锁失效，已拒绝写入过期状态")

    async def initialize(self) -> None:
        """创建连接池并执行PING，Redis不可用时让应用启动失败。"""
        # 延迟导入使内存自测不依赖本机已经安装redis-py。
        from redis.asyncio import Redis

        self._client = Redis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
            # 远程Redis连接可能被网络设备回收；借出空闲连接前先PING，
            # 读超时后自动换连接重试一次，避免首条用户消息直接失败。
            socket_keepalive=True,
            health_check_interval=30,
            socket_connect_timeout=5,
            socket_timeout=8,
            retry_on_timeout=True,
        )
        await self._client.ping()

    @timed("redis.context.read")
    async def get_or_create(
        self,
        session_id: str,
        conversation_id: str | None = None,
        user_id: str | None = None,
    ) -> ConversationState:
        """从Redis读取会话，不存在时返回一个尚未保存的新状态。"""
        client = self._require_client()
        payload = await client.get(self._key(session_id))
        if payload:
            state = ConversationState.from_dict(json.loads(payload))
            bind_owner(state, conversation_id, user_id)
            return state
        return ConversationState(
            session_id=session_id,
            conversation_id=conversation_id,
            user_id=user_id,
        )

    @timed("redis.context.write")
    async def save(self, state: ConversationState) -> None:
        """把会话写入Redis并刷新TTL。"""
        client = self._require_client()
        payload = json.dumps(state.to_dict(), ensure_ascii=False, separators=(",", ":"))
        await self._fenced_set(self._key(state.session_id), payload, self.ttl_seconds, state.session_id)

    async def delete(self, session_id: str) -> None:
        """主动结束会话时删除Redis状态。"""
        await self._require_client().delete(self._key(session_id))

    async def health_check(self) -> bool:
        """通过PING检查Redis连接。"""
        try:
            return bool(await self._require_client().ping())
        except Exception:
            return False

    async def close(self) -> None:
        """关闭redis-py连接池。"""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _key(self, session_id: str) -> str:
        """生成带业务前缀的Redis Key。"""
        return f"{self.key_prefix}{session_id}"

    def _require_client(self) -> Any:
        """确保initialize已经执行，避免出现难排查的空连接错误。"""
        if self._client is None:
            raise RuntimeError("RedisSessionStore尚未初始化")
        return self._client
