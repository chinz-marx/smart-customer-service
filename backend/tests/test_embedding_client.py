import asyncio

from app.config import Settings
from app.retrieval.embedding import DoubaoEmbeddingClient


def test_large_text_model_uses_text_embedding_endpoint() -> None:
    """纯文本模型必须走/embeddings，并传入Redis索引要求的维度。"""
    settings = Settings(
        embedding_model="doubao-embedding-large-text-250515",
        embedding_dimension=2048,
    )
    client = DoubaoEmbeddingClient(settings)
    try:
        endpoint, payload = client._build_request("退款规则")
        assert endpoint == "/embeddings"
        assert payload["input"] == ["退款规则"]
        assert payload["dimensions"] == 2048
    finally:
        asyncio.run(client.close())


def test_vision_model_keeps_multimodal_endpoint() -> None:
    """保留vision兼容路径，便于后续继续执行两种模型的A/B评测。"""
    settings = Settings(embedding_model="doubao-embedding-vision-251215")
    client = DoubaoEmbeddingClient(settings)
    try:
        endpoint, payload = client._build_request("退款规则")
        assert endpoint == "/embeddings/multimodal"
        assert payload["input"] == [{"type": "text", "text": "退款规则"}]
        assert "dimensions" not in payload
    finally:
        asyncio.run(client.close())
