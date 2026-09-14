"""显式执行的真实ASR联调；只发送指定测试WAV或1秒静音，不调用聊天。

python scripts/check_asr_stream.py [--wav synthetic.wav] [--gateway ws://localhost:8000/api/speech/stream]
密钥从backend/.env读取，输出仅包含状态和耗时，不打印密钥或识别正文。
"""
import argparse
import asyncio
import json
import sys
import time
import uuid
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus

from app.config import Settings
from app.speech.protocol import AsrProtocolError, audio_packet, parse_response, start_packet


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--wav", type=Path)
    parser.add_argument("--gateway")
    parser.add_argument("--expect", default="")
    parser.add_argument("--trailing-silence", type=float, default=0, help="Seconds of silence after the test speech")
    args = parser.parse_args()
    if args.wav:
        with wave.open(str(args.wav), "rb") as source:
            if (source.getframerate(), source.getnchannels(), source.getsampwidth()) != (16000, 1, 2):
                raise ValueError("Test WAV must be 16kHz mono PCM16")
            pcm = source.readframes(source.getnframes())
    else:
        pcm = bytes(32000)
    pcm += bytes(int(max(0, min(45, args.trailing_silence)) * 16000) * 2)
    settings = Settings()
    request_id = str(uuid.uuid4())
    headers = {"X-Api-Key": settings.asr_api_key, "X-Api-Resource-Id": settings.asr_resource_id,
               "X-Api-Request-Id": request_id, "X-Api-Connect-Id": request_id, "X-Api-Sequence": "-1"}
    started = time.monotonic()
    try:
        async with connect(
            args.gateway or settings.asr_ws_url,
            additional_headers=None if args.gateway else headers,
            origin="http://localhost:5173" if args.gateway else None,
            open_timeout=8, close_timeout=1, compression=None, proxy=None,
        ) as ws:
            print(json.dumps({"connected_ms": round((time.monotonic() - started) * 1000)}), flush=True)
            if args.gateway:
                await ws.send(json.dumps({"type": "start", "format": "pcm_s16le", "sample_rate": 16000, "channels": 1}))
                ready = json.loads(await ws.recv())
                if ready.get("type") != "ready":
                    print(json.dumps({"error": ready.get("message", "No ready event")}, ensure_ascii=True))
                    return 1
            else:
                await ws.send(start_packet(request_id))
            capture_started = time.monotonic()
            finished_at = None

            async def send():
                nonlocal finished_at
                sequence = 2
                for offset in range(0, len(pcm), 3200):
                    chunk = pcm[offset:offset + 3200]
                    await ws.send(chunk if args.gateway else audio_packet(chunk, sequence))
                    sequence += 1
                    await asyncio.sleep(max(0, capture_started + (offset + len(chunk)) / 32000 - time.monotonic()))
                finished_at = time.monotonic()
                await ws.send(json.dumps({"type": "finish"}) if args.gateway else audio_packet(b"", sequence, final=True))

            task = asyncio.create_task(send())
            first_text_ms = None
            final_text = ""
            saw_partial = False
            try:
                async with asyncio.timeout(len(pcm) / 32000 + 15):
                    async for raw in ws:
                        if args.gateway:
                            payload = json.loads(raw)
                            if payload.get("type") == "error":
                                raise RuntimeError(payload.get("message"))
                            text, final = payload.get("text", ""), payload.get("type") == "final"
                        else:
                            result = parse_response(raw)
                            text, final = result.text or "", result.final
                        if text:
                            final_text = text
                            if first_text_ms is None:
                                first_text_ms = round((time.monotonic() - capture_started) * 1000)
                            saw_partial |= not final and finished_at is None
                        if final:
                            matched = not args.expect or args.expect in final_text
                            print(json.dumps({"final": True, "text_length": len(final_text), "expected_match": matched,
                                              "partial_before_finish": saw_partial, "first_text_ms": first_text_ms,
                                              "finish_wait_ms": round((time.monotonic() - (finished_at or capture_started)) * 1000)}, ensure_ascii=True))
                            await task
                            return 0 if matched else 1
                return 1
            finally:
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    except InvalidStatus as exc:
        print(json.dumps({"error": "ASR handshake rejected", "http_status": exc.response.status_code}))
        return 1
    except Exception as exc:
        # Protocol errors use sanitized messages; other exceptions may carry headers.
        print(json.dumps({"error_type": type(exc).__name__,
                          "protocol_reason": str(exc) if isinstance(exc, AsrProtocolError) else ""}))
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
