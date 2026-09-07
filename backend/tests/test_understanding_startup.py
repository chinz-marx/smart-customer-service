from unittest.mock import Mock

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app


def test_lifespan_prepares_and_reuses_model_client_without_inference(monkeypatch):
    client_factory = Mock()
    monkeypatch.setattr("app.understanding.service.ChatOpenAI", client_factory)
    settings = Settings(
        understanding_mode="llm", understanding_api_key="test-startup-key",
        session_store_backend="memory", persistence_backend="memory",
        nacos_enabled=False, mcp_enabled=False, semantic_search_enabled=False,
        learning_enabled=False,
    )
    app = create_app(settings)
    with TestClient(app):
        service = app.state.chat_service.agent.orchestrator.understanding_service
        client_factory.assert_called_once()
        adapter = service._context_llm
        assert adapter is not None
        service.initialize()
        assert service._get_context_llm() is adapter
        client_factory.assert_called_once()
        client_factory.return_value.with_structured_output.assert_called_once()
        adapter.ainvoke.assert_not_called()


def test_keyword_startup_does_not_create_model_client(monkeypatch):
    client_factory = Mock()
    monkeypatch.setattr("app.understanding.service.ChatOpenAI", client_factory)
    settings = Settings(
        understanding_mode="keyword", session_store_backend="memory", persistence_backend="memory",
        nacos_enabled=False, mcp_enabled=False, semantic_search_enabled=False, learning_enabled=False,
    )
    with TestClient(create_app(settings)):
        client_factory.assert_not_called()
