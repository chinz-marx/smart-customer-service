import asyncio
import gzip
import json
import struct
from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.speech.protocol import AsrProtocolError, audio_packet, parse_response, start_packet
from app.speech.router import create_speech_router


def response_packet(text=None, *, flags=1, compressed=True, code=None):
    body = {} if text is None else {"result": {"text": text}}
    if code is not None:
        body["code"] = code
    data = json.dumps(body).encode()
    data = gzip.compress(data) if compressed else data
    header = bytes((0x11, 0x90 | flags, 0x10 | int(compressed), 0))
    sequence = struct.pack(">i", -2 if flags & 2 else 2) if flags & 1 else b""
    return header + sequence + struct.pack(">I", len(data)) + data


def test_protocol_audio_and_initial_config():
    initial = start_packet("test-id")
    assert initial[:4] == b"\x11\x11\x11\x00"
    assert struct.unpack(">i", initial[4:8])[0] == 1
    body = json.loads(gzip.decompress(initial[12:]))
    assert body["audio"] == {"format": "pcm", "codec": "raw", "rate": 16000, "bits": 16, "channel": 1}
    assert body["request"]["enable_nonstream"] is False
    assert body["request"]["result_type"] == "full"
    audio = b"\x01\x02" * 1600
    packet = audio_packet(audio, 7, final=True)
    assert packet[:4] == b"\x11\x23\x01\x00"
    assert struct.unpack(">i", packet[4:8])[0] == -7
    assert gzip.decompress(packet[12:]) == audio


@pytest.mark.parametrize("flags", [0, 1, 2, 3])
@pytest.mark.parametrize("compressed", [False, True])
def test_response_flags_with_and_without_sequence(flags, compressed):
    result = parse_response(response_packet("订单查询。", flags=flags, compressed=compressed))
    assert result.text == "订单查询。"
    assert result.final == bool(flags & 2)


def test_protocol_errors_do_not_expose_provider_payload():
    with pytest.raises(AsrProtocolError):
        parse_response(b"bad")
    with pytest.raises(AsrProtocolError):
        parse_response(response_packet("text")[:-1])
    with pytest.raises(AsrProtocolError, match="rejected"):
        parse_response(response_packet(code=45000000))
    with pytest.raises(AsrProtocolError, match="code=401") as error:
        parse_response(b"\x11\xf0\x10\x00" + struct.pack(">II", 401, 6) + b"secret")
    assert "secret" not in str(error.value)


class FakeUpstream:
    def __init__(self, *, final=True):
        self.incoming = asyncio.Queue()
        self.sent = []
        self.closed = False
        self.final = final

    async def send(self, data):
        self.sent.append(data)
        if data[1] >> 4 == 2:
            if data[1] & 2:
                if self.final:
                    await self.incoming.put(response_packet("查询订单进度。", flags=3))
                    # Fast upstream may deliver final before send() resumes.
                    await asyncio.sleep(0.001)
            else:
                await self.incoming.put(response_packet("查询订单"))

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.incoming.get()


def make_client(monkeypatch, *, key="test-asr-key", final=True):
    upstreams = []

    @asynccontextmanager
    async def connect_fake(url, **kwargs):
        assert url.endswith("/bigmodel_async")
        assert kwargs["additional_headers"]["X-Api-Key"] == key
        assert kwargs["additional_headers"]["X-Api-Resource-Id"] == "volc.seedasr.sauc.duration"
        upstream = FakeUpstream(final=final)
        upstreams.append(upstream)
        try:
            yield upstream
        finally:
            upstream.closed = True

    monkeypatch.setattr("app.speech.router.connect", connect_fake)
    settings = Settings(_env_file=None, asr_api_key=key, asr_finish_timeout_seconds=0.05)
    app = FastAPI()
    app.include_router(create_speech_router(settings))
    return TestClient(app), upstreams


def start_browser(ws):
    ws.send_json({"type": "start", "format": "pcm_s16le", "sample_rate": 16000, "channels": 1})
    assert ws.receive_json()["type"] == "ready"


def test_websocket_streams_before_finish_and_drains_last_text(monkeypatch):
    client, upstreams = make_client(monkeypatch)
    with client, client.websocket_connect("/api/speech/stream", headers={"origin": "http://localhost:5173"}) as ws:
        start_browser(ws)
        ws.send_bytes(b"\x00\x00" * 1600)
        partial = ws.receive_json()
        assert partial["type"] == "partial"  # Returned before browser sends finish.
        assert partial["text"] == "查询订单"
        ws.send_bytes(b"\x01\x00" * 30)  # Last short packet must not be dropped.
        ws.send_json({"type": "finish"})
        final = ws.receive_json()
        assert final["type"] == "final"
        assert final["text"] == "查询订单进度。"
        assert final["request_id"] == partial["request_id"]
    assert upstreams[0].closed
    assert gzip.decompress(upstreams[0].sent[-2][12:]) == b"\x01\x00" * 30
    assert struct.unpack(">i", upstreams[0].sent[-1][4:8])[0] < 0


@pytest.mark.parametrize("action", ["cancel", "disconnect"])
def test_cancel_and_disconnect_close_upstream(monkeypatch, action):
    client, upstreams = make_client(monkeypatch)
    with client, client.websocket_connect("/api/speech/stream", headers={"origin": "http://localhost:5173"}) as ws:
        start_browser(ws)
        if action == "cancel":
            ws.send_json({"type": "cancel"})
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
    assert upstreams[0].closed


def test_final_timeout_preserves_partial_and_closes(monkeypatch):
    client, upstreams = make_client(monkeypatch, final=False)
    with client, client.websocket_connect("/api/speech/stream", headers={"origin": "http://localhost:5173"}) as ws:
        start_browser(ws)
        ws.send_bytes(b"\x00\x00" * 1600)
        assert ws.receive_json()["type"] == "partial"
        ws.send_json({"type": "finish"})
        assert "超时" in ws.receive_json()["message"]
    assert upstreams[0].closed


@pytest.mark.parametrize("audio", [b"odd", b"", b"\0" * 6402])
def test_invalid_audio_is_rejected(monkeypatch, audio):
    client, upstreams = make_client(monkeypatch)
    with client, client.websocket_connect("/api/speech/stream", headers={"origin": "http://localhost:5173"}) as ws:
        start_browser(ws)
        ws.send_bytes(audio)
        assert ws.receive_json()["type"] == "error"
    assert len(upstreams[0].sent) == 1


def test_origin_and_missing_configuration_fail_closed(monkeypatch):
    client, upstreams = make_client(monkeypatch, key="")
    with client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect("/api/speech/stream", headers={"origin": "https://untrusted.example"}):
                pass
        with client.websocket_connect("/api/speech/stream", headers={"origin": "http://localhost:5173"}) as ws:
            assert "尚未配置" in ws.receive_json()["message"]
    assert not upstreams
