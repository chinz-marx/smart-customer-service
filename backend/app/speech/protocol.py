"""豆包 ASR V3 二进制协议；浏览器侧协议与供应商协议分离。"""
from __future__ import annotations

import gzip
import json
import struct
import zlib
from dataclasses import dataclass

MAX_RESPONSE_BYTES = 1024 * 1024


class AsrProtocolError(Exception):
    pass


def _packet(message_type: int, payload: bytes, sequence: int, *, json_payload: bool = False) -> bytes:
    flags = 3 if sequence < 0 else 1
    compressed = gzip.compress(payload, compresslevel=1, mtime=0)
    header = bytes((0x11, (message_type << 4) | flags, (0x10 if json_payload else 0) | 1, 0))
    return header + struct.pack(">iI", sequence, len(compressed)) + compressed


def start_packet(request_id: str) -> bytes:
    payload = {
        "user": {"uid": request_id},
        "audio": {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1},
        "request": {
            "model_name": "bigmodel", "enable_itn": True, "enable_punc": True,
            "enable_ddc": True, "show_utterances": True, "enable_nonstream": False,
            # 每次返回完整识别快照，前端替换当前录音的文字，避免重复追加。
            "result_type": "full",
        },
    }
    return _packet(1, json.dumps(payload).encode(), 1, json_payload=True)


def audio_packet(audio: bytes, sequence: int, *, final: bool = False) -> bytes:
    return _packet(2, audio, -abs(sequence) if final else sequence)


@dataclass(frozen=True)
class AsrResponse:
    text: str | None
    final: bool


def parse_response(data: bytes) -> AsrResponse:
    if len(data) < 8 or data[0] >> 4 != 1:
        raise AsrProtocolError("invalid header")
    offset = (data[0] & 15) * 4
    message_type, flags = data[1] >> 4, data[1] & 15
    serialization, compression = data[2] >> 4, data[2] & 15
    if offset < 4 or offset > len(data):
        raise AsrProtocolError("invalid header size")

    def read_int(signed: bool = False) -> int:
        nonlocal offset
        if offset + 4 > len(data):
            raise AsrProtocolError("truncated packet")
        result = int.from_bytes(data[offset:offset + 4], "big", signed=signed)
        offset += 4
        return result

    sequence = read_int(True) if flags & 1 else 0
    if flags & 4:
        read_int()  # Optional event identifier.
    if message_type == 15:
        code = read_int()
        # 不传播供应商原始错误正文，可能包含请求信息。
        raise AsrProtocolError(f"upstream error code={code}")
    if message_type != 9:
        raise AsrProtocolError("unsupported response type")
    size = read_int()
    if size > MAX_RESPONSE_BYTES or offset + size != len(data):
        raise AsrProtocolError("invalid payload size")
    payload = data[offset:]
    if compression == 1:
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        payload = decoder.decompress(payload, MAX_RESPONSE_BYTES + 1)
        if len(payload) > MAX_RESPONSE_BYTES or not decoder.eof or decoder.unused_data:
            raise AsrProtocolError("invalid compressed payload")
    elif compression != 0:
        raise AsrProtocolError("unsupported compression")
    if serialization != 1:
        raise AsrProtocolError("expected JSON response")
    try:
        body = json.loads(payload)
        if not isinstance(body, dict):
            raise ValueError("expected object")
        if body.get("code", 0) not in (0, 1000, 20000000):
            raise AsrProtocolError("upstream rejected audio")
        result = body.get("result", {})
        text = result.get("text") if isinstance(result, dict) else None
        if text is not None and not isinstance(text, str):
            raise ValueError("expected text")
    except (ValueError, UnicodeError) as exc:
        raise AsrProtocolError("invalid JSON response") from exc
    return AsrResponse(text=text, final=bool(flags & 2) or sequence < 0)
