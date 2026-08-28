from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import yaml
from redis.asyncio import Redis


# scripts不是Python包，显式加入backend根目录以兼容Windows和Linux直接运行。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import Settings
from app.evaluation.knowledge_retrieval_evaluator import (
    KnowledgeRetrievalCase,
    RetrievalCandidate,
    build_retrieval_report,
    calculate_retrieval_metrics,
    evaluate_knowledge_retrieval,
    evaluate_retrieval_acceptance,
    render_retrieval_markdown,
)
from app.retrieval.embedding import DoubaoEmbeddingClient, vector_to_bytes


DEFAULT_DATASET = BACKEND_DIR / "evaluation" / "knowledge_retrieval_cases.yaml"
DEFAULT_REPORT_DIR = BACKEND_DIR / "evaluation" / "reports"


class RedisVectorRetriever:
    """调用真实Embedding模型和Redis Search，返回未经过阈值过滤的TopK候选。"""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._embedding = DoubaoEmbeddingClient(settings)
        self._redis: Redis | None = None

    async def initialize(self) -> None:
        """建立Redis连接，并确认知识索引存在。"""
        self._redis = Redis.from_url(self.settings.redis_url, decode_responses=False)
        await self._redis.ping()
        await self._redis.execute_command("FT.INFO", self.settings.knowledge_index_name)

    async def close(self) -> None:
        """释放模型HTTP连接池和Redis连接池。"""
        await self._embedding.close()
        if self._redis is not None:
            await self._redis.aclose()
            self._redis = None

    async def retrieve(
        self, question: str, intent: str, top_k: int
    ) -> tuple[RetrievalCandidate, ...]:
        """按意图与审核状态过滤，再执行KNN向量查询。"""
        vector_blob = vector_to_bytes(await self._embedding.embed(question))
        query = (
            f"(@intent:{{{intent}}} @status:{{approved}})"
            f"=>[KNN {top_k} @embedding $vector AS vector_distance]"
        )
        raw = await self._require_redis().execute_command(
            "FT.SEARCH",
            self.settings.knowledge_index_name,
            query,
            "PARAMS",
            "2",
            "vector",
            vector_blob,
            "SORTBY",
            "vector_distance",
            "ASC",
            "RETURN",
            "4",
            "id",
            "knowledge_id",
            "chunk_no",
            "vector_distance",
            "DIALECT",
            "2",
        )
        return self._parse_candidates(raw)

    def _parse_candidates(self, raw: list[Any]) -> tuple[RetrievalCandidate, ...]:
        """把Redis RESP数组转换成强类型候选，并校验source_id格式。"""
        candidates: list[RetrievalCandidate] = []
        for index in range(1, len(raw), 2):
            fields = raw[index + 1]
            values = {
                self._decode(fields[field_index]): self._decode(fields[field_index + 1])
                for field_index in range(0, len(fields), 2)
            }
            source_id = values["id"]
            source_parts = source_id.split(":")
            if len(source_parts) != 3:
                raise ValueError(f"知识source_id格式错误：{source_id}")
            candidates.append(
                RetrievalCandidate(
                    source_id=source_id,
                    knowledge_id=int(values.get("knowledge_id") or source_parts[0]),
                    version_id=int(source_parts[1]),
                    chunk_no=int(values.get("chunk_no") or source_parts[2]),
                    distance=float(values["vector_distance"]),
                )
            )
        return tuple(candidates)

    @staticmethod
    def _decode(value: Any) -> str:
        return value.decode("utf-8") if isinstance(value, bytes) else str(value)

    def _require_redis(self) -> Redis:
        if self._redis is None:
            raise RuntimeError("RedisVectorRetriever尚未初始化")
        return self._redis


def parse_args() -> argparse.Namespace:
    """定义Windows PowerShell和Linux shell通用的命令行参数。"""
    parser = argparse.ArgumentParser(description="运行知识向量召回评测")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_REPORT_DIR)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--concurrency", type=int, default=3)
    parser.add_argument(
        "--check-thresholds",
        action="store_true",
        help="验收未通过时返回退出码2，适合接入CI。",
    )
    return parser.parse_args()


def load_dataset(path: Path) -> tuple[dict[str, Any], list[KnowledgeRetrievalCase]]:
    """安全读取并校验知识召回数据集。"""
    with path.resolve().open("r", encoding="utf-8") as file:
        payload = yaml.safe_load(file) or {}
    if not isinstance(payload, dict) or not isinstance(payload.get("cases"), list):
        raise ValueError("知识召回数据集必须包含cases列表")

    cases: list[KnowledgeRetrievalCase] = []
    seen_ids: set[str] = set()
    for raw_case in payload["cases"]:
        case = KnowledgeRetrievalCase(
            case_id=str(raw_case["id"]),
            text=str(raw_case["text"]),
            expected_match=bool(raw_case["expected_match"]),
            expected_chunk_no=(
                int(raw_case["expected_chunk_no"])
                if raw_case.get("expected_chunk_no") is not None
                else None
            ),
        )
        if case.case_id in seen_ids:
            raise ValueError(f"样本ID重复：{case.case_id}")
        if case.expected_match and case.expected_chunk_no is None:
            raise ValueError(f"正样本必须标注expected_chunk_no：{case.case_id}")
        if not case.expected_match and case.expected_chunk_no is not None:
            raise ValueError(f"负样本不能标注expected_chunk_no：{case.case_id}")
        seen_ids.add(case.case_id)
        cases.append(case)
    return payload, cases


async def find_published_target(
    settings: Settings, target_title: str
) -> dict[str, Any]:
    """从PostgreSQL定位页面发布的当前版本，避免在数据集中写死自增ID。"""
    connection = await asyncpg.connect(
        settings.database_url.replace("postgresql+asyncpg://", "postgresql://"),
        timeout=10,
    )
    try:
        row = await connection.fetchrow(
            "SELECT k.id AS knowledge_id, k.knowledge_code, k.current_version_id, "
            "v.version_no, length(v.content) AS content_chars, "
            "(SELECT COUNT(*) FROM business.kb_knowledge_chunk c "
            " WHERE c.knowledge_id=k.id AND c.version_id=v.id) AS chunk_count "
            "FROM business.kb_knowledge k "
            "JOIN business.kb_knowledge_version v ON v.id=k.current_version_id "
            "WHERE k.status=1 AND v.title=$1 "
            "ORDER BY v.published_at DESC LIMIT 1",
            target_title,
        )
        if row is None:
            raise RuntimeError(f"找不到已发布目标知识：{target_title}")
        return dict(row)
    finally:
        await connection.close()


async def run(
    args: argparse.Namespace,
) -> tuple[Path, Path, dict[str, Any], dict[str, Any]]:
    """执行真实评测并生成JSON明细与Markdown摘要。"""
    dataset_path = args.dataset.resolve()
    dataset, cases = load_dataset(dataset_path)
    target = dataset.get("target") or {}
    target_title = str(target.get("title") or "").strip()
    intent = str(target.get("intent") or "").strip()
    if not target_title or not intent:
        raise ValueError("target必须配置title和intent")

    settings = Settings(semantic_search_enabled=True)
    if not settings.has_real_embedding_api_key:
        raise RuntimeError("请先在backend/.env配置真实EMBEDDING_API_KEY")
    published = await find_published_target(settings, target_title)
    expected_chunks = int(target.get("expected_chunks", 0))
    if expected_chunks and int(published["chunk_count"]) != expected_chunks:
        raise RuntimeError(
            "目标知识切片数量与数据集不一致："
            f"expected={expected_chunks}, actual={published['chunk_count']}"
        )

    retriever = RedisVectorRetriever(settings)
    await retriever.initialize()
    try:
        results = await evaluate_knowledge_retrieval(
            cases=cases,
            retriever=retriever,
            intent=intent,
            top_k=args.top_k,
            concurrency=args.concurrency,
        )
    finally:
        await retriever.close()

    threshold_candidates = [
        float(value) for value in dataset.get("threshold_candidates", [])
    ]
    if not threshold_candidates:
        raise ValueError("数据集必须配置threshold_candidates")
    acceptance_thresholds = dataset.get("acceptance_thresholds") or {}
    max_false_positive_rate = float(
        acceptance_thresholds.get(
            "max_configured_negative_false_positive_rate", 0.10
        )
    )
    metrics = calculate_retrieval_metrics(
        results=results,
        target_knowledge_id=int(published["knowledge_id"]),
        configured_threshold=settings.knowledge_distance_threshold,
        threshold_candidates=threshold_candidates,
        max_negative_false_positive_rate=max_false_positive_rate,
    )
    acceptance = evaluate_retrieval_acceptance(metrics, acceptance_thresholds)
    generated_at = datetime.now(timezone.utc)
    report = build_retrieval_report(
        results=results,
        metrics=metrics,
        metadata={
            "generated_at": generated_at.isoformat(),
            "dataset": str(dataset_path.relative_to(BACKEND_DIR)),
            "dataset_version": dataset.get("version", 1),
            "target_title": target_title,
            "target_knowledge_id": int(published["knowledge_id"]),
            "target_knowledge_code": published["knowledge_code"],
            "target_version_id": int(published["current_version_id"]),
            "target_version_no": int(published["version_no"]),
            "target_content_chars": int(published["content_chars"]),
            "target_chunks": int(published["chunk_count"]),
            "intent": intent,
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
    json_path = args.output_dir / f"knowledge-retrieval-{stamp}.json"
    markdown_path = args.output_dir / f"knowledge-retrieval-{stamp}.md"
    json_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    markdown_path.write_text(render_retrieval_markdown(report), encoding="utf-8")
    return json_path, markdown_path, metrics, acceptance


def print_summary(
    json_path: Path,
    markdown_path: Path,
    metrics: dict[str, Any],
    acceptance: dict[str, Any],
) -> None:
    """在终端打印最关键结果，完整距离明细保留在报告中。"""
    configured = metrics["configured_threshold_result"]
    recommended = metrics["recommended_threshold"]
    print(f"样本数: {metrics['total_cases']}")
    print(f"知识Recall@1: {metrics['knowledge_recall_at_1'] * 100:.2f}%")
    print(f"知识Recall@3: {metrics['knowledge_recall_at_3'] * 100:.2f}%")
    print(f"分片Recall@1: {metrics['chunk_recall_at_1'] * 100:.2f}%")
    print(f"分片Recall@3: {metrics['chunk_recall_at_3'] * 100:.2f}%")
    print(
        f"当前阈值{metrics['configured_threshold']:.3f}: "
        f"正样本召回={configured['positive_recall'] * 100:.2f}%, "
        f"负样本误命中={configured['negative_false_positive_rate'] * 100:.2f}%"
    )
    print(
        f"建议候选阈值{recommended['threshold']:.3f}: "
        f"正样本召回={recommended['positive_recall'] * 100:.2f}%, "
        f"负样本误命中={recommended['negative_false_positive_rate'] * 100:.2f}%"
    )
    print(f"自动验收: {'通过' if acceptance['passed'] else '未通过'}")
    print(f"JSON报告: {json_path.relative_to(BACKEND_DIR)}")
    print(f"Markdown报告: {markdown_path.relative_to(BACKEND_DIR)}")


def main() -> None:
    """命令行入口；只有显式检查门槛时才以退出码2表示验收失败。"""
    args = parse_args()
    json_path, markdown_path, metrics, acceptance = asyncio.run(run(args))
    print_summary(json_path, markdown_path, metrics, acceptance)
    if args.check_thresholds and not acceptance["passed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
