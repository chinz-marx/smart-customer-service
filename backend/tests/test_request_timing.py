import asyncio
import json
from unittest.mock import patch

import pytest

from app.observability.timing import (
    ChatTimingMiddleware, bind_request_id, current_timing, measured,
)


def test_concurrent_streams_keep_independent_timings_and_identical_bytes():
    async def scenario():
        async def app(scope, receive, send):
            bind_request_id(scope["test_id"])
            await measured("model", asyncio.sleep(0))
            await send({"type": "http.response.start", "status": 200})
            await send({"type": "http.response.body", "body": b"event: delta\ndata: hello\n\n", "more_body": True})
            await measured("save", asyncio.sleep(0))
            await send({"type": "http.response.body", "body": b"event: done\ndata: {}\n\n", "more_body": False})

        async def run(request_id):
            sent = []
            async def send(message):
                sent.append(message)
            async def receive():
                return {"type": "http.request"}
            await ChatTimingMiddleware(app)(
                {"type": "http", "path": "/api/chat/stream", "test_id": request_id}, receive, send,
            )
            assert current_timing.get() is None
            return sent

        with patch("app.observability.timing.logger.info") as log:
            streams = await asyncio.gather(run("one"), run("two"))
            rows = [json.loads(call.args[0]) for call in log.call_args_list]
        assert streams[0] == streams[1]
        assert streams[0][1]["body"] == b"event: delta\ndata: hello\n\n"
        assert {row["request_id"] for row in rows} == {"one", "two"}
        for row in rows:
            assert row["first_answer_ms"] <= row["done_ms"] <= row["total_ms"]
            assert [s["name"] for s in row["spans"]].count("model") == 1
            assert [s["name"] for s in row["spans"]].count("save") == 1
            assert "hello" not in json.dumps(row)
    asyncio.run(scenario())


def test_cancelled_request_is_logged_and_cancellation_propagates():
    async def scenario():
        async def cancelled():
            raise asyncio.CancelledError()
        async def app(scope, receive, send):
            await measured("storage", cancelled())
        with patch("app.observability.timing.logger.info") as log:
            with pytest.raises(asyncio.CancelledError):
                await ChatTimingMiddleware(app)({"type": "http", "path": "/api/chat"}, None, None)
            row = json.loads(log.call_args.args[0])
        assert row["outcome"] == "CancelledError"
        assert row["spans"][0]["outcome"] == "CancelledError"
        assert current_timing.get() is None
    asyncio.run(scenario())
