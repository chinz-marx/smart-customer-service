import json

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_memory_mode_api_flow() -> None:
    """使用固定测试用户验证聊天、反馈、历史记录和工单接口。"""
    settings = Settings(
        doubao_api_key="YOUR_TEST_KEY",
        session_store_backend="memory",
        persistence_backend="memory",
        nacos_enabled=False,
        mcp_enabled=False,
        demo_user_id="api-test-user",
        app_reload=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        health = client.get("/api/health")
        assert health.status_code == 200
        assert health.json()["session_store"] == "memory"
        assert health.json()["persistence"] == "memory"

        chat = client.post("/api/chat", json={"message": "我要转人工"})
        assert chat.status_code == 200
        payload = chat.json()
        assert payload["conversation_id"]
        assert payload["message_id"]
        assert payload["ticket_id"]

        feedback = client.post(
            "/api/feedback",
            json={
                "conversation_id": payload["conversation_id"],
                "message_id": payload["message_id"],
                "feedback_type": "helpful",
                "rating": 5,
            },
        )
        assert feedback.status_code == 200
        assert feedback.json()["feedback_type"] == "helpful"

        conversations = client.get("/api/conversations")
        assert conversations.status_code == 200
        assert conversations.json()[0]["status"] == "handoff"

        messages = client.get(f"/api/conversations/{payload['conversation_id']}/messages")
        assert messages.status_code == 200
        assert [item["role"] for item in messages.json()] == ["user", "assistant"]

def test_memory_mode_stream_api_persists_completed_answer() -> None:
    """SSE接口应先发送回答增量，再发送带消息ID的完成事件并正常落库。"""
    settings = Settings(
        doubao_api_key="YOUR_TEST_KEY",
        understanding_api_key="YOUR_TEST_KEY",
        session_store_backend="memory",
        persistence_backend="memory",
        nacos_enabled=False,
        mcp_enabled=False,
        demo_user_id="stream-api-test-user",
        app_reload=False,
    )
    app = create_app(settings)

    with TestClient(app) as client:
        response = client.post("/api/chat/stream", json={"message": "我要转人工"})

        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")

        events: list[tuple[str, dict[str, object]]] = []
        for block in response.text.strip().split("\n\n"):
            lines = block.splitlines()
            event = next(line[7:] for line in lines if line.startswith("event: "))
            data = next(line[6:] for line in lines if line.startswith("data: "))
            events.append((event, json.loads(data)))

        assert [event for event, _ in events] == ["delta", "done"]
        assert "转人工" in str(events[0][1]["content"])

        done = events[1][1]
        assert done["message_id"]
        assert done["conversation_id"]
        assert done["ticket_id"]

        messages = client.get(f"/api/conversations/{done['conversation_id']}/messages")
        assert messages.status_code == 200
        assert [item["role"] for item in messages.json()] == ["user", "assistant"]
