from __future__ import annotations

import asyncio
import sys
import uuid
from pathlib import Path


# scripts目录不是Python包，显式加入backend根目录以兼容Windows和Linux。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.customer_service import CustomerServiceAgent
from app.retrieval.service import RedisSemanticAnswerService


async def verify_knowledge() -> list[tuple[str, str, str, float]]:
    """验证相近问法能够命中三类审核知识。"""
    settings = Settings(semantic_search_enabled=True)
    service = RedisSemanticAnswerService(settings)
    await service.initialize()
    cases = (
        ("刚注册的人怎样参加新人活动", "activity_rules"),
        ("退款审核过了钱几天能回来", "refund_request"),
        ("会员的券要去什么地方领", "benefits_query"),
    )
    results: list[tuple[str, str, str, float]] = []
    try:
        for question, intent in cases:
            lookup = await service.lookup(question, intent)
            if not lookup.hit:
                nearest = await service._search(
                    index_name=settings.knowledge_index_name,
                    vector_blob=lookup.vector_blob or b"",
                    intent=intent,
                    statuses="approved",
                    top_k=settings.knowledge_top_k,
                    distance_threshold=1.0,
                    provider="redis-search:knowledge",
                )
                detail = (
                    f"id={nearest.source_id}, distance={nearest.distance:.6f}"
                    if nearest
                    else "没有候选"
                )
                raise AssertionError(f"知识库未命中: {question}; 最近结果: {detail}")
            if lookup.hit.provider != "redis-search:knowledge":
                raise AssertionError(f"命中了错误来源: {lookup.hit.provider}")
            results.append((question, lookup.hit.source_id, lookup.hit.provider, lookup.hit.distance))
        return results
    finally:
        await service.close()


async def inspect_negative_distances() -> list[tuple[str, str, float]]:
    """采集同意图无答案问题的最近距离，用于防止阈值过宽。"""
    settings = Settings(semantic_search_enabled=True)
    service = RedisSemanticAnswerService(settings)
    await service.initialize()
    cases = (
        ("活动页面一直白屏怎么修复", "activity_rules"),
        ("会员头像在哪里更换", "benefits_query"),
        ("退款页面验证码收不到怎么办", "refund_request"),
    )
    results: list[tuple[str, str, float]] = []
    try:
        for question, intent in cases:
            lookup = await service.lookup(question, intent)
            if lookup.hit:
                raise AssertionError(f"负样本被知识库误命中: {question}")
            nearest = await service._search(
                index_name=settings.knowledge_index_name,
                vector_blob=lookup.vector_blob or b"",
                intent=intent,
                statuses="approved",
                top_k=settings.knowledge_top_k,
                distance_threshold=1.0,
                provider="redis-search:knowledge",
            )
            if not nearest:
                raise AssertionError(f"无法取得负样本最近距离: {question}")
            results.append((question, nearest.source_id, nearest.distance))
        return results
    finally:
        await service.close()


async def cleanup_langcache_test_data(service: RedisSemanticAnswerService) -> None:
    """只清理本脚本产生的测试Key，让闭环验证可以重复执行。"""
    client = service._require_redis()
    prefixes = (
        service.settings.langcache_key_prefix,
        service.settings.langcache_gap_key_prefix,
    )
    for prefix in prefixes:
        async for key in client.scan_iter(match=f"{prefix}*"):
            if await client.type(key) != b"hash":
                continue
            raw_question = await client.hget(key, "question")
            question = raw_question.decode("utf-8") if isinstance(raw_question, bytes) else ""
            if "会员电子纪念章如何补发" not in question:
                continue
            await client.delete(key, key + b":actors")


async def verify_langcache() -> tuple[bool, bool, str, str, float, float]:
    """用两个不同会话触发高频门槛，并验证后续请求直接命中LangCache。"""
    # -1让知识库在本次验证中必定不命中；正式.env阈值不会被修改。
    settings = Settings(
        semantic_search_enabled=True,
        knowledge_distance_threshold=-1.0,
        langcache_frequency_threshold=2,
        langcache_distance_threshold=0.20,
        langcache_ttl_seconds=300,
    )
    service = RedisSemanticAnswerService(settings)
    await service.initialize()
    unique = uuid.uuid4().hex[:8]
    question = f"会员电子纪念章如何补发，测试编号{unique}"
    answer = "这是LangCache高频缺口闭环测试答案。"
    await cleanup_langcache_test_data(service)
    try:
        first_lookup = await service.lookup(question, "benefits_query")
        if first_lookup.hit:
            raise AssertionError("首次缺口问题不应命中LangCache")

        first_written = await service.record_generated_answer(
            question=question,
            answer=answer,
            intent="benefits_query",
            actor_id=f"test-session-a-{unique}",
            lookup=first_lookup,
        )
        second_written = await service.record_generated_answer(
            question=question,
            answer=answer,
            intent="benefits_query",
            actor_id=f"test-session-b-{unique}",
            lookup=first_lookup,
        )
        similar_question = f"会员的电子纪念章丢了怎么重新领，编号{unique}"
        cached_lookup = await service.lookup(similar_question, "benefits_query")
        if not cached_lookup.hit:
            raise AssertionError("达到频次门槛后相近问法没有命中LangCache")
        if cached_lookup.hit.provider != "redis-search:langcache":
            raise AssertionError(f"命中了错误来源: {cached_lookup.hit.provider}")
        if cached_lookup.hit.answer != answer:
            raise AssertionError("LangCache返回答案与写入答案不一致")

        # 使用真实UnderstandingService再走一次完整编排，验证意图识别之后直接命中LangCache，
        # 并且不调用回答LLM。这里使用内存会话，不启动FastAPI服务。
        agent = CustomerServiceAgent(
            settings,
            semantic_answer_service=service,
        )
        orchestration = await agent.handle(
            message=similar_question,
            session_id=f"orchestration-{unique}",
            history=[],
        )
        if orchestration.intent != "benefits_query":
            raise AssertionError(f"端到端意图识别错误: {orchestration.intent}")
        if orchestration.provider != "redis-search:langcache":
            raise AssertionError(f"端到端没有直接命中LangCache: {orchestration.provider}")
        if orchestration.answer != answer:
            raise AssertionError("端到端LangCache答案不一致")

        unrelated_lookup = await service.lookup("会员头像在哪里修改", "benefits_query")
        if unrelated_lookup.hit:
            raise AssertionError("LangCache负样本被错误命中")
        unrelated_nearest = await service._search(
            index_name=settings.langcache_index_name,
            vector_blob=unrelated_lookup.vector_blob or b"",
            intent="benefits_query",
            statuses="approved|unreviewed",
            top_k=1,
            distance_threshold=1.0,
            provider="redis-search:langcache",
        )
        if not unrelated_nearest:
            raise AssertionError("无法取得LangCache负样本距离")
        return (
            first_written,
            second_written,
            cached_lookup.hit.provider,
            orchestration.intent,
            cached_lookup.hit.distance,
            unrelated_nearest.distance,
        )
    finally:
        await cleanup_langcache_test_data(service)
        await service.close()


async def main() -> None:
    """运行真实Redis Search与LangCache闭环验证。"""
    knowledge_results = await verify_knowledge()
    negative_results = await inspect_negative_distances()
    (
        first_written,
        second_written,
        provider,
        orchestration_intent,
        cache_positive_distance,
        cache_negative_distance,
    ) = await verify_langcache()
    for question, source_id, source, distance in knowledge_results:
        print(f"知识命中: {question} -> {source_id} ({source}, distance={distance:.6f})")
    for question, source_id, distance in negative_results:
        print(f"负样本最近项: {question} -> {source_id} (distance={distance:.6f})")
    print(
        "LangCache闭环: "
        f"首次写入={first_written}, 达到门槛写入={second_written}, 命中来源={provider}, "
        f"识别意图={orchestration_intent}, 改写距离={cache_positive_distance:.6f}, "
        f"负样本距离={cache_negative_distance:.6f}"
    )


if __name__ == "__main__":
    asyncio.run(main())
