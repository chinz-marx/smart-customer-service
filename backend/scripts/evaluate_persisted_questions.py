from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg


# 兼容 Windows PowerShell 和 Linux shell 直接执行脚本。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.config import Settings
from app.evaluation.knowledge_retrieval_evaluator import (
    KnowledgeRetrievalCase,
    build_retrieval_report,
    calculate_retrieval_metrics,
    evaluate_knowledge_retrieval,
    evaluate_retrieval_acceptance,
    render_retrieval_markdown,
)
from evaluate_knowledge_retrieval import RedisVectorRetriever


DEFAULT_REPORT_DIR = BACKEND_DIR / "evaluation" / "reports"
NEGATIVE_QUESTIONS = (
    "今天天气怎么样？",
    "帮我写一段年会主持词。",
    "Java虚拟机的垃圾回收算法有哪些？",
    "从北京到上海坐高铁需要多久？",
    "推荐一部适合周末看的电影。",
)


def parse_args() -> argparse.Namespace:
    """定义真实数据库评测所需的命令行参数。"""
    parser = argparse.ArgumentParser(description="评测数据库已发布标准问法的Redis召回效果")
    parser.add_argument("--title", required=True, help="页面中已审批发布的知识标题")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
    return parser.parse_args()


async def load_published_cases(
    settings: Settings, title: str
) -> tuple[dict[str, Any], list[KnowledgeRetrievalCase]]:
    """从PostgreSQL读取当前发布版本及其已同步标准问法。"""
    connection = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
        timeout=10,
    )
    try:
        target_row = await connection.fetchrow(
            "SELECT k.id AS knowledge_id, k.knowledge_code, k.current_version_id, "
            "v.version_no, v.intent_code, length(v.content) AS content_chars, "
            "(SELECT COUNT(*) FROM business.kb_knowledge_chunk c "
            " WHERE c.version_id=v.id) AS chunk_count "
            "FROM business.kb_knowledge k "
            "JOIN business.kb_knowledge_version v ON v.id=k.current_version_id "
            # Java枚举中version_status=2表示已发布，1表示待审批。
            "WHERE k.status=1 AND v.version_status=2 AND v.title=$1 "
            "ORDER BY v.published_at DESC LIMIT 1",
            title,
        )
        if target_row is None:
            raise RuntimeError(f"找不到已发布知识：{title}")
        if not str(target_row["intent_code"] or "").strip():
            raise RuntimeError("目标知识没有intent_code，无法执行带意图过滤的Redis查询")

        question_rows = await connection.fetch(
            "SELECT q.id, q.question_text, c.chunk_no "
            "FROM business.kb_knowledge_question q "
            "JOIN business.kb_knowledge_chunk c ON c.id=q.chunk_id "
            "WHERE q.version_id=$1 AND q.sync_status=1 AND q.redis_key IS NOT NULL "
            "ORDER BY c.chunk_no, q.question_no",
            target_row["current_version_id"],
        )
        if not question_rows:
            raise RuntimeError("目标知识没有已同步标准问法，请先检查Outbox发布状态")

        cases = [
            KnowledgeRetrievalCase(
                case_id=f"db-question-{row['id']}",
                text=row["question_text"],
                expected_match=True,
                expected_chunk_no=int(row["chunk_no"]),
            )
            for row in question_rows
        ]
        cases.extend(
            KnowledgeRetrievalCase(
                case_id=f"negative-{index}",
                text=text,
                expected_match=False,
            )
            for index, text in enumerate(NEGATIVE_QUESTIONS, start=1)
        )
        return dict(target_row), cases
    finally:
        await connection.close()


async def run(args: argparse.Namespace) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    """执行真实Embedding与Redis Search评测并保存报告。"""
    settings = Settings(semantic_search_enabled=True)
    if not settings.has_real_embedding_api_key:
        raise RuntimeError("请先在backend/.env配置真实EMBEDDING_API_KEY")

    target, cases = await load_published_cases(settings, args.title.strip())
    retriever = RedisVectorRetriever(settings)
    await retriever.initialize()
    try:
        results = await evaluate_knowledge_retrieval(
            cases=cases,
            retriever=retriever,
            intent=str(target["intent_code"]),
            top_k=args.top_k,
            concurrency=args.concurrency,
        )
    finally:
        await retriever.close()

    metrics = calculate_retrieval_metrics(
        results=results,
        target_knowledge_id=int(target["knowledge_id"]),
        configured_threshold=settings.knowledge_distance_threshold,
        threshold_candidates=[0.20, 0.25, 0.30, 0.35, 0.40, 0.45, 0.50, 0.55, 0.60],
        max_negative_false_positive_rate=0.20,
    )
    acceptance_thresholds = {
        "min_knowledge_recall_at_3": 0.95,
        "min_chunk_recall_at_3": 0.90,
        "min_configured_positive_recall": 0.90,
        "max_configured_negative_false_positive_rate": 0.20,
        "max_error_count": 0,
    }
    acceptance = evaluate_retrieval_acceptance(metrics, acceptance_thresholds)
    generated_at = datetime.now(timezone.utc)
    report = build_retrieval_report(
        results=results,
        metrics=metrics,
        metadata={
            "generated_at": generated_at.isoformat(),
            "dataset": "PostgreSQL已发布标准问法 + 固定跨领域负样本",
            "target_title": args.title.strip(),
            "target_knowledge_id": int(target["knowledge_id"]),
            "target_knowledge_code": target["knowledge_code"],
            "target_version_id": int(target["current_version_id"]),
            "target_version_no": int(target["version_no"]),
            "target_content_chars": int(target["content_chars"]),
            "target_chunks": int(target["chunk_count"]),
            "persisted_question_count": len(cases) - len(NEGATIVE_QUESTIONS),
            "negative_count": len(NEGATIVE_QUESTIONS),
            "intent": target["intent_code"],
            "embedding_model": settings.embedding_model,
            "embedding_dimension": settings.embedding_dimension,
            "redis_index": settings.knowledge_index_name,
            "top_k": args.top_k,
            "concurrency": args.concurrency,
        },
        acceptance=acceptance,
    )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    stamp = generated_at.strftime("%Y%m%d-%H%M%S")
    json_path = args.output_dir / f"persisted-question-retrieval-{stamp}.json"
    markdown_path = args.output_dir / f"persisted-question-retrieval-{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    markdown_path.write_text(render_retrieval_markdown(report), encoding="utf-8")
    return json_path, markdown_path, metrics, acceptance


def main() -> None:
    """脚本入口打印核心指标，完整样本明细保存在报告文件中。"""
    args = parse_args()
    json_path, markdown_path, metrics, acceptance = asyncio.run(run(args))
    configured = metrics["configured_threshold_result"]
    print(f"样本数: {metrics['total_cases']}")
    print(f"知识Recall@1: {metrics['knowledge_recall_at_1'] * 100:.2f}%")
    print(f"分片Recall@1: {metrics['chunk_recall_at_1'] * 100:.2f}%")
    print(f"当前阈值正样本召回: {configured['positive_recall'] * 100:.2f}%")
    print(f"当前阈值负样本误命中: {configured['negative_false_positive_rate'] * 100:.2f}%")
    print(f"平均耗时: {metrics['average_latency_ms']:.2f}ms")
    print(f"自动验收: {'通过' if acceptance['passed'] else '未通过'}")
    print(f"JSON报告: {json_path.relative_to(BACKEND_DIR)}")
    print(f"Markdown报告: {markdown_path.relative_to(BACKEND_DIR)}")


if __name__ == "__main__":
    main()
