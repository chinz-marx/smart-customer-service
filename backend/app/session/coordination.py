from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar


logger = logging.getLogger("smart_customer_service.session")
RENEW_INTERVAL_SECONDS = 15
_held: ContextVar[tuple] = ContextVar("dialogue_locks", default=())
_leases: ContextVar[tuple] = ContextVar("dialogue_redis_leases", default=())


def active_redis_lease(store, key=None):
    for store_id, session_key, task, lock in reversed(_leases.get()):
        if store_id == id(store) and task is asyncio.current_task() and (key is None or key == session_key):
            return lock
    return None


class MemoryLocks:
    def __init__(self):
        self.entries = {}

    @asynccontextmanager
    async def hold(self, key):
        identity = (id(self), key, asyncio.current_task())
        if identity in _held.get():
            yield
            return
        lock, count = self.entries.get(key, (asyncio.Lock(), 0))
        self.entries[key] = (lock, count + 1)
        acquired = False
        token = None
        try:
            await asyncio.wait_for(lock.acquire(), timeout=10)
            acquired = True
            token = _held.set((*_held.get(), identity))
            yield
        finally:
            if token is not None:
                _held.reset(token)
            if acquired:
                lock.release()
            _, count = self.entries[key]
            if count == 1:
                del self.entries[key]
            else:
                self.entries[key] = (lock, count - 1)


@asynccontextmanager
async def redis_session_lock(store, key):
    identity = (id(store), key, asyncio.current_task())
    if identity in _held.get():
        yield
        return
    lock = store._require_client().lock(
        store._key(key) + ":lock", timeout=60, blocking_timeout=10, thread_local=False,
    )
    if not await lock.acquire():
        raise TimeoutError("会话正在处理，请稍后重试")
    owner = asyncio.current_task()
    token = _held.set((*_held.get(), identity))
    lease_token = _leases.set((*_leases.get(), (id(store), key, owner, lock)))

    async def renew():
        try:
            while True:
                await asyncio.sleep(RENEW_INTERVAL_SECONDS)
                await lock.extend(60, replace_ttl=True)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("会话锁续租失败，终止当前请求以防止并发写入")
            owner.cancel()

    renewal = asyncio.create_task(renew(), name="renew-dialogue-lock")
    try:
        yield
        if not await lock.owned():
            raise RuntimeError("会话锁已失效")
    finally:
        renewal.cancel()
        with suppress(asyncio.CancelledError):
            await renewal
        _held.reset(token)
        _leases.reset(lease_token)
        try:
            await lock.release()
        except Exception:
            logger.warning("释放会话锁失败；锁将自动过期", exc_info=True)
