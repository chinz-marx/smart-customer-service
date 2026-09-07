"""Request-scoped timings, including storage before orchestration and SSE sends."""
from __future__ import annotations

import json
import logging
import time
import uuid
from contextlib import asynccontextmanager, contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from functools import wraps


logger = logging.getLogger("smart_customer_service.request_timing")


@dataclass
class RequestTiming:
    started: float = field(default_factory=time.perf_counter)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    spans: list = field(default_factory=list)
    marks: dict = field(default_factory=dict)

    def elapsed(self):
        return round((time.perf_counter() - self.started) * 1000, 3)


current_timing: ContextVar[RequestTiming | None] = ContextVar("request_timing", default=None)


@contextmanager
def stage(name):
    trace = current_timing.get()
    if trace is None:
        yield
        return
    start = trace.elapsed()
    outcome = "ok"
    try:
        yield
    except BaseException as exc:
        outcome = type(exc).__name__
        raise
    finally:
        end = trace.elapsed()
        trace.spans.append({"name": name, "start_ms": start, "end_ms": end,
                            "duration_ms": round(end - start, 3), "outcome": outcome})


def timed(name):
    def decorate(fn):
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            with stage(name(*args, **kwargs) if callable(name) else name):
                return await fn(*args, **kwargs)
        return wrapper
    return decorate


async def measured(name, awaitable):
    with stage(name):
        return await awaitable


@asynccontextmanager
async def timed_lock(lock):
    # Preserve the wrapped context manager's exception and cancellation semantics.
    class MeasuredLock:
        async def __aenter__(self):
            return await measured("session.lock.acquire", lock.__aenter__())

        async def __aexit__(self, *exc):
            return await measured("session.lock.release", lock.__aexit__(*exc))

    async with MeasuredLock() as value:
        yield value


def bind_request_id(request_id):
    trace = current_timing.get()
    if trace is not None:
        trace.request_id = request_id


class ChatTimingMiddleware:
    """Pure ASGI: preserves streaming and propagates context into child tasks."""

    def __init__(self, app):
        self.app = app
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(message)s"))
            logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope.get("path") not in {"/api/chat", "/api/chat/stream"}:
            return await self.app(scope, receive, send)
        trace = RequestTiming()
        token = current_timing.set(trace)
        status = None
        outcome = "ok"

        async def tracked_send(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                trace.marks["headers_ms"] = trace.elapsed()
            if message["type"] == "http.response.body" and message.get("body"):
                body = message["body"]
                if scope["path"] == "/api/chat" or body.startswith(b"event: delta\n"):
                    trace.marks.setdefault("first_answer_ms", trace.elapsed())
                if body.startswith(b"event: done\n"):
                    trace.marks["done_ms"] = trace.elapsed()
                if body.startswith(b"event: error\n"):
                    trace.marks["stream_error_ms"] = trace.elapsed()
            with stage("response.send"):
                await send(message)

        try:
            await self.app(scope, receive, tracked_send)
        except BaseException as exc:
            outcome = type(exc).__name__
            raise
        finally:
            logger.info(json.dumps({"event": "chat_timing", "request_id": trace.request_id,
                                   "path": scope["path"], "status": status, "outcome": outcome,
                                   "total_ms": trace.elapsed(), **trace.marks,
                                   "spans": sorted(trace.spans, key=lambda s: s["start_ms"])},
                                  ensure_ascii=False))
            current_timing.reset(token)
