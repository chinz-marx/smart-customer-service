from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from contextlib import suppress
from urllib.parse import urlsplit

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from app.config import Settings
from app.speech.protocol import AsrProtocolError, audio_packet, parse_response, start_packet

logger = logging.getLogger("smart_customer_service.speech")
BYTES_PER_SECOND = 32000
MAX_PACKET_BYTES = 6400  # 200ms PCM，浏览器默认每100ms发送一次。


class SpeechInputError(Exception):
    pass


class SpeechCancelled(Exception):
    pass


async def relay_speech(browser: WebSocket, upstream, settings: Settings, request_id: str) -> None:
    """读写双协程，不等待每包应答；浏览器断开时立即取消供应商连接。"""
    started = time.monotonic()
    sent_bytes = 0
    latest_text = ""
    first_text_ms: int | None = None
    finish_sent = asyncio.Event()

    async def send_audio() -> None:
        nonlocal sent_bytes
        sequence = 2
        while True:
            event = await asyncio.wait_for(browser.receive(), timeout=10)
            if event["type"] == "websocket.disconnect":
                raise SpeechCancelled()
            audio = event.get("bytes")
            if audio is not None:
                if finish_sent.is_set():
                    raise SpeechInputError("录音已结束，请重新开始")
                if not audio or len(audio) > MAX_PACKET_BYTES or len(audio) % 2:
                    raise SpeechInputError("音频格式不正确，请重新录音")
                sent_bytes += len(audio)
                if sent_bytes > settings.asr_max_duration_seconds * BYTES_PER_SECOND:
                    raise SpeechInputError("录音超过时长限制，请分段输入")
                await asyncio.wait_for(upstream.send(audio_packet(audio, sequence)), timeout=5)
                sequence += 1
                continue
            raw = event.get("text", "")
            if len(raw) > 256:
                raise SpeechInputError("无效的语音控制消息")
            try:
                control = json.loads(raw)
            except ValueError as exc:
                raise SpeechInputError("无效的语音控制消息") from exc
            kind = control.get("type") if isinstance(control, dict) else None
            if kind == "cancel":
                raise SpeechCancelled()
            if kind != "finish" or finish_sent.is_set():
                raise SpeechInputError("无效的语音控制消息")
            if not sent_bytes:
                raise SpeechInputError("没有采集到声音，请重新录音")
            finish_sent.set()
            await asyncio.wait_for(upstream.send(audio_packet(b"", sequence, final=True)), timeout=5)
            # 继续监听断开/取消，不能在等待最终识别时留下孤立的供应商请求。

    async def receive_text() -> None:
        nonlocal latest_text, first_text_ms
        async for message in upstream:
            if not isinstance(message, bytes):
                raise AsrProtocolError("expected binary packet")
            result = parse_response(message)
            changed = result.text is not None and result.text != latest_text
            if result.text is not None:
                latest_text = result.text
            if latest_text and first_text_ms is None:
                first_text_ms = round((time.monotonic() - started) * 1000)
            if result.final:
                if not finish_sent.is_set():
                    raise AsrProtocolError("unexpected upstream termination")
                await browser.send_json({"type": "final", "text": latest_text, "request_id": request_id})
                return
            if changed:
                await browser.send_json({"type": "partial", "text": latest_text, "request_id": request_id})
        raise AsrProtocolError("upstream closed before final result")

    async def finish_deadline() -> None:
        await finish_sent.wait()
        await asyncio.sleep(settings.asr_finish_timeout_seconds)
        raise SpeechInputError("等待最终识别结果超时，请重新录音")

    await asyncio.wait_for(upstream.send(start_packet(request_id)), timeout=5)
    await browser.send_json({
        "type": "ready", "request_id": request_id,
        "max_duration_seconds": settings.asr_max_duration_seconds,
        "sample_rate": 16000, "packet_ms": 100,
    })
    tasks = [asyncio.create_task(fn()) for fn in (send_audio, receive_text, finish_deadline)]
    try:
        async with asyncio.timeout(settings.asr_max_duration_seconds + settings.asr_finish_timeout_seconds + 5):
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("asr_timing request_id=%s audio_ms=%d first_text_ms=%s total_ms=%d",
                    request_id, sent_bytes * 1000 // BYTES_PER_SECOND,
                    first_text_ms, round((time.monotonic() - started) * 1000))


def create_speech_router(settings: Settings) -> APIRouter:
    router = APIRouter()
    active: set[str] = set()

    @router.websocket("/api/speech/stream")
    async def speech_stream(browser: WebSocket) -> None:
        # WebSocket不受CORS中间件保护，显式检查网页来源。
        origin = browser.headers.get("origin", "")
        same_origin = origin in {f"http://{browser.headers.get('host')}", f"https://{browser.headers.get('host')}"}
        if not same_origin and origin not in settings.cors_origin_list:
            await browser.close(code=1008)
            return
        await browser.accept()
        request_id = str(uuid.uuid4())
        if not settings.asr_api_key or settings.asr_api_key.startswith("YOUR_"):
            await browser.send_json({"type": "error", "message": "语音识别尚未配置，请联系管理员"})
            await browser.close(code=1011)
            return
        if len(active) >= settings.asr_max_connections:
            await browser.send_json({"type": "error", "message": "语音服务繁忙，请稍后重试"})
            await browser.close(code=1013)
            return
        active.add(request_id)
        close_code = 1000
        try:
            raw = await asyncio.wait_for(browser.receive_text(), timeout=10)
            if len(raw) > 512:
                raise SpeechInputError("无效的语音开始消息")
            try:
                start = json.loads(raw)
            except ValueError as exc:
                raise SpeechInputError("无效的语音开始消息") from exc
            if not isinstance(start, dict) or any(start.get(key) != value for key, value in {
                "type": "start", "format": "pcm_s16le", "sample_rate": 16000, "channels": 1,
            }.items()):
                raise SpeechInputError("不支持的音频格式")
            if urlsplit(settings.asr_ws_url).scheme != "wss":
                raise SpeechInputError("语音服务地址配置不正确")
            headers = {
                "X-Api-Key": settings.asr_api_key,
                "X-Api-Resource-Id": settings.asr_resource_id,
                "X-Api-Request-Id": request_id,
                "X-Api-Connect-Id": request_id,
                "X-Api-Sequence": "-1",
            }
            async with connect(
                settings.asr_ws_url, additional_headers=headers,
                open_timeout=settings.asr_connect_timeout_seconds, close_timeout=1,
                max_size=1024 * 1024, max_queue=8, compression=None, proxy=None,
            ) as upstream:
                await relay_speech(browser, upstream, settings, request_id)
        except (WebSocketDisconnect, SpeechCancelled):
            pass
        except Exception as exc:
            close_code = 1011
            if isinstance(exc, SpeechInputError):
                message = str(exc)
            elif isinstance(exc, TimeoutError):
                message = "语音连接超时，请重新录音"
            elif isinstance(exc, InvalidStatus) and exc.response.status_code in (401, 403):
                message = "语音服务鉴权失败，请检查 ASR 密钥和资源开通状态"
            elif isinstance(exc, (AsrProtocolError, ConnectionClosed)):
                message = "语音识别中断，请重新录音"
            else:
                message = "暂时无法连接语音服务，请稍后重试"
            # 不记录完整异常、请求头、音频或识别正文。
            logger.warning("asr_failed request_id=%s error_type=%s protocol_reason=%s", request_id,
                           type(exc).__name__, str(exc) if isinstance(exc, AsrProtocolError) else "")
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await browser.send_json({"type": "error", "message": message, "request_id": request_id})
        finally:
            active.discard(request_id)
            with suppress(WebSocketDisconnect, RuntimeError, OSError):
                await browser.close(code=close_code)

    return router
