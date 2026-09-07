from __future__ import annotations

import asyncio

from app.config import Settings
from app.retrieval.knowledge_publisher import RedisKnowledgePublisher


class _FakeRedis:
    def __init__(self) -> None:
        self.pinged = False
        self.closed = False

    async def ping(self) -> None:
        self.pinged = True

    async def aclose(self) -> None:
        self.closed = True


def test_knowledge_publisher_enables_tcp_keepalive(monkeypatch) -> None:
    captured: dict[str, object] = {}
    fake_redis = _FakeRedis()

    def fake_from_url(url: str, **kwargs: object) -> _FakeRedis:
        captured["url"] = url
        captured.update(kwargs)
        return fake_redis

    monkeypatch.setattr(
        "app.retrieval.knowledge_publisher.Redis.from_url",
        fake_from_url,
    )
    publisher = RedisKnowledgePublisher(Settings(redis_url="redis://127.0.0.1:6379/0"))

    async def scenario() -> None:
        await publisher.initialize()

        assert fake_redis.pinged is True
        assert captured["socket_keepalive"] is True
        assert captured["health_check_interval"] == 30
        assert captured["socket_connect_timeout"] == 5
        assert captured["socket_timeout"] == 8
        assert captured["retry_on_timeout"] is True

        await publisher.close()
        assert fake_redis.closed is True

    asyncio.run(scenario())
