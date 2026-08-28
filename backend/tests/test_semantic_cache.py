import asyncio

import pytest

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.llm.generator import GenerateAnswerResult
from app.retrieval.embedding import vector_to_bytes
from app.retrieval.schemas import SemanticAnswerHit, SemanticLookup
from app.retrieval.service import RedisSemanticAnswerService


class FakeSemanticAnswerService:
    """单元测试替身：不连接Redis，只记录编排器是否正确调用双检索。"""

    def __init__(self, hit: SemanticAnswerHit | None = None) -> None:
        self.hit = hit
        self.lookup_calls = 0
        self.record_calls = 0

    async def initialize(self) -> None:
        pass

    async def lookup(self, question: str, intent: str) -> SemanticLookup:
        self.lookup_calls += 1
        return SemanticLookup(hit=self.hit, vector_blob=b"test-vector")

    async def record_generated_answer(
        self,
        question: str,
        answer: str,
        intent: str,
        actor_id: str,
        lookup: SemanticLookup,
    ) -> bool:
        self.record_calls += 1
        return True

    async def health_check(self) -> bool:
        return True

    async def close(self) -> None:
        pass


@pytest.fixture
def keyword_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """使用关键词理解，保证测试不请求真实LLM或Redis。"""
    monkeypatch.setenv("UNDERSTANDING_MODE", "keyword")
    monkeypatch.setenv("DOUBAO_API_KEY", "YOUR_TEST_KEY")
    monkeypatch.setenv("SEMANTIC_SEARCH_ENABLED", "false")
    return Settings()


def test_knowledge_hit_skips_answer_model(
    keyword_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """审核知识命中后必须直接返回，不能再调用回答模型。"""
    semantic = FakeSemanticAnswerService(
        SemanticAnswerHit(
            answer="活动结束时间以活动详情页为准。",
            provider="redis-search:knowledge",
            distance=0.05,
            source_id="activity_end_time",
        )
    )
    agent = CustomerServiceAgent(
        keyword_settings,
        semantic_answer_service=semantic,
    )

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("知识库命中后不应调用回答模型")

    monkeypatch.setattr(agent.orchestrator.answer_generator, "generate", fail_if_called)
    answer, _, provider, _ = asyncio.run(agent.reply("活动什么时候结束", None, []))

    assert answer == "活动结束时间以活动详情页为准。"
    assert provider == "redis-search:knowledge"
    assert semantic.lookup_calls == 1


def test_successful_llm_answer_records_langcache_gap(
    keyword_settings: Settings,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """双检索未命中且LLM成功时，应记录高频缺口候选。"""
    semantic = FakeSemanticAnswerService()
    agent = CustomerServiceAgent(
        keyword_settings,
        semantic_answer_service=semantic,
    )

    async def successful_answer(*args, **kwargs):
        return GenerateAnswerResult(answer="这是模型生成的活动说明。", provider="doubao")

    monkeypatch.setattr(agent.orchestrator.answer_generator, "generate", successful_answer)
    answer, _, provider, _ = asyncio.run(agent.reply("活动参与条件是什么", None, []))

    assert answer == "这是模型生成的活动说明。"
    assert provider == "doubao"
    assert semantic.lookup_calls == 1
    assert semantic.record_calls == 1


def test_dynamic_tool_does_not_query_semantic_cache(keyword_settings: Settings) -> None:
    """订单等动态业务必须优先走Tool，不能被知识库或LangCache覆盖。"""
    semantic = FakeSemanticAnswerService()
    agent = CustomerServiceAgent(
        keyword_settings,
        semantic_answer_service=semantic,
    )

    answer, _, provider, _ = asyncio.run(
        agent.reply("查询订单 ORDER_123456", None, [])
    )

    # Java服务未启动时Tool可以降级，但仍然绝不能用静态语义缓存代替动态查询。
    assert provider != "redis-search:knowledge"
    assert provider != "redis-search:langcache"
    assert answer
    assert semantic.lookup_calls == 0


def test_vector_to_bytes_uses_float32() -> None:
    """每个FLOAT32占4字节，向量序列化结果应跨平台稳定。"""
    assert len(vector_to_bytes([0.1, 0.2, 0.3])) == 12


def test_order_knowledge_is_allowed_for_composite_queries() -> None:
    """订单实时查询仍走Tool，但订单说明必须允许在组合问题中进入知识检索。"""
    settings = Settings()

    assert "order_query" in settings.semantic_cache_intent_set


def test_generic_knowledge_route_is_allowed_and_searches_legacy_intents() -> None:
    """新版统一知识意图必须可查询旧意图下已发布的知识。"""
    settings = Settings()

    assert "knowledge_query" in settings.semantic_cache_intent_set
    query = RedisSemanticAnswerService._build_search_query(
        "knowledge_query",
        "approved",
        3,
    )

    assert "@status:{approved}" in query
    assert "@intent:" not in query


def test_legacy_knowledge_route_keeps_intent_filter() -> None:
    """旧意图兼容路由仍应限定意图，避免扩大原有查询范围。"""
    query = RedisSemanticAnswerService._build_search_query(
        "activity_rules",
        "approved",
        3,
    )

    assert "@intent:{activity_rules}" in query
    assert "@status:{approved}" in query
