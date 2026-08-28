from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.retrieval.chunk_splitter import create_knowledge_chunk_router


def test_split_endpoint_returns_server_generated_chunks() -> None:
    app = FastAPI()
    app.include_router(create_knowledge_chunk_router())
    client = TestClient(app)

    response = client.post(
        "/api/knowledge/chunks/split",
        json={"content": "退款审核通过后通常在1至7个工作日内原路到账。"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "chunks": [
            {
                "chunk_no": 0,
                "content": "退款审核通过后通常在1至7个工作日内原路到账。",
            }
        ]
    }


def test_split_endpoint_rejects_blank_content() -> None:
    app = FastAPI()
    app.include_router(create_knowledge_chunk_router())
    client = TestClient(app)

    response = client.post(
        "/api/knowledge/chunks/split",
        json={"content": "   "},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "知识正文不能为空"
