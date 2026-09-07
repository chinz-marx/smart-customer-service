import asyncio
import os
import uuid
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.session.store import ConversationState, RedisSessionStore


class FakeRedis:
    def __init__(self):
        self.data = {}
        self.acquisitions = 0
        self.fail_renewal = False

    async def get(self, key):
        return self.data.get(key)

    async def set(self, key, value, **kwargs):
        self.data[key] = value

    async def eval(self, script, numkeys, lock_key, data_key, token, payload, ttl):
        if self.data.get(lock_key) != token:
            return 0
        self.data[data_key] = payload
        return 1

    def lock(self, name, **kwargs):
        client = self

        class Lock:
            def __init__(self):
                self.name = name
                self.local = SimpleNamespace(token=uuid.uuid4().hex)

            async def acquire(self):
                client.acquisitions += 1
                client.data[name] = self.local.token
                return True

            async def extend(self, *args, **kwargs):
                if client.fail_renewal:
                    raise ConnectionError("lease lost")

            async def owned(self):
                return client.data.get(name) == self.local.token

            async def release(self):
                if not await self.owned():
                    raise RuntimeError("not owner")
                del client.data[name]

        return Lock()


def test_redis_reentrant_lock_and_atomic_fencing():
    async def scenario():
        store = RedisSessionStore("redis://unused", 1800)
        client = FakeRedis()
        store._client = client
        with pytest.raises(RuntimeError):
            async with store.lock("s"):
                async with store.lock("s"):
                    state = ConversationState(session_id="s", current_intent="original")
                    await store.save(state)
                assert client.acquisitions == 1
                # Simulate a newer worker acquiring the expired lease before this save.
                client.data[store._key("s") + ":lock"] = "new-worker-token"
                state.current_intent = "stale"
                with pytest.raises(RuntimeError):
                    await store.save(state)
                with pytest.raises(RuntimeError):
                    await store.save_receipt("request", {"status": "completed"})
        restored = await store.get_or_create("s")
        assert restored.current_intent == "original"
        assert client.data[store._key("s") + ":lock"] == "new-worker-token"
    asyncio.run(scenario())


def test_redis_renewal_failure_cancels_inflight_turn(monkeypatch):
    import app.session.coordination as coordination
    monkeypatch.setattr(coordination, "RENEW_INTERVAL_SECONDS", 0.001)

    async def scenario():
        store = RedisSessionStore("redis://unused", 1800)
        client = FakeRedis()
        client.fail_renewal = True
        store._client = client

        async def turn():
            async with store.lock("s"):
                await asyncio.Event().wait()

        task = asyncio.create_task(turn())
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert store._key("s") + ":lock" not in client.data
    asyncio.run(scenario())


@pytest.mark.skipif(os.environ.get("RUN_DIALOGUE_REDIS_TESTS") != "1", reason="requires explicitly enabled real Redis integration")
def test_real_redis_cross_instance_serialization_receipt_and_expiry():
    async def scenario():
        prefix = f"test:dialogue:{uuid.uuid4().hex}:"
        stores = [RedisSessionStore(Settings().redis_url, 2, prefix) for _ in range(2)]
        try:
            for store in stores:
                await store.initialize()

            async def turn(store):
                async with store.lock("session"):
                    state = await store.get_or_create("session", user_id="test-user")
                    await asyncio.sleep(0.01)
                    state.touch()
                    await store.save(state)

            await asyncio.gather(*(turn(stores[i % 2]) for i in range(6)))
            state = await stores[0].get_or_create("session", user_id="test-user")
            assert state.turn_count == 6
            async with stores[0].lock("session"):
                await stores[0].save_receipt("receipt", {"status": "completed"})
            assert await stores[1].get_receipt("receipt") == {"status": "completed"}
            await asyncio.sleep(2.1)
            assert (await stores[1].get_or_create("session", user_id="test-user")).turn_count == 0
        finally:
            for store in stores:
                if store._client:
                    await store._client.delete(prefix + "session", prefix + "request:receipt")
                await store.close()
    asyncio.run(scenario())
