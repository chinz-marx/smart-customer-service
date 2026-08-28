from __future__ import annotations

import sys
from pathlib import Path

from fastapi.testclient import TestClient


# scripts目录不是Python包，显式加入backend根目录以兼容Windows和Linux。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.main import create_app


def main() -> int:
    """在进程内验证FastAPI、真实存储和Redis知识检索，不监听网络端口。"""
    with TestClient(create_app()) as client:
        health = client.get("/api/health")
        health.raise_for_status()
        health_payload = health.json()
        if health_payload.get("semantic_search_status") != "ok":
            raise AssertionError(f"语义检索健康检查失败: {health_payload}")

        response = client.post(
            "/api/chat",
            json={
                "message": "退款审核已经通过，通常几天能退回来",
                "history": [],
            },
        )
        response.raise_for_status()
        payload = response.json()
        if payload.get("provider") != "redis-search:knowledge":
            raise AssertionError(f"聊天请求没有命中审核知识库: {payload}")
        if "1至7个工作日" not in payload.get("answer", ""):
            raise AssertionError(f"知识库答案不符合预期: {payload}")

        print(
            "API闭环通过: "
            f"status={health_payload['status']}, "
            f"semantic={health_payload['semantic_search_status']}, "
            f"provider={payload['provider']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
