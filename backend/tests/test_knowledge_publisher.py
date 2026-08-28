from datetime import datetime, timedelta, timezone

import pytest
from pydantic import ValidationError

from app.retrieval.chunk_splitter import KnowledgeTextSplitter
from app.retrieval.knowledge_publisher import KnowledgePublishRequest


def test_short_faq_keeps_complete_answer() -> None:
    splitter = KnowledgeTextSplitter(target_size=20, max_size=40, overlap=5)
    chunks = splitter.split("退款审核通过后通常在1至7个工作日内原路到账。")
    assert len(chunks) == 1
    assert chunks[0].content.startswith("退款审核通过")


def test_long_rule_prefers_sentence_boundaries_and_has_stable_hash() -> None:
    splitter = KnowledgeTextSplitter(target_size=18, max_size=30, overlap=4)
    content = "第一条规则需要实名认证。第二条规则每天只能参加一次。第三条规则奖励三日内到账。"
    chunks = splitter.split(content)
    assert len(chunks) >= 2
    assert all(len(chunk.content) <= 30 for chunk in chunks)
    assert all(len(chunk.content_hash) == 64 for chunk in chunks)
    assert [chunk.chunk_no for chunk in chunks] == list(range(len(chunks)))


def test_invalid_splitter_configuration_is_rejected() -> None:
    try:
        KnowledgeTextSplitter(target_size=100, max_size=80, overlap=10)
    except ValueError as error:
        assert "切片参数" in str(error)
    else:
        raise AssertionError("非法切片参数必须抛出ValueError")


def make_publish_request(chunks: list[dict[str, object]]) -> dict[str, object]:
    """构造最小合法发布请求，单个测试只需要覆盖关心的分片字段。"""
    now = datetime.now(timezone.utc)
    return {
        "knowledge_id": 1,
        "knowledge_code": "KB-TEST",
        "version_id": 2,
        "version_no": 1,
        "title": "测试规则",
        "content": "测试规则正文",
        "category": "活动规则",
        "tags": [],
        "intent": "general_consultation",
        "effective_at": now - timedelta(minutes=1),
        "chunks": chunks,
    }


def test_reviewed_chunks_and_questions_are_preserved() -> None:
    """Python必须保留Java发送的人工审核顺序，不能再次自行切片。"""
    payload = KnowledgePublishRequest.model_validate(
        make_publish_request(
            [
                {"chunk_no": 0, "content": "第一段规则", "questions": [
                    {"question_id": 101, "question_no": 0, "text": "第一段怎么规定？"}
                ]},
                {"chunk_no": 1, "content": "第二段规则", "questions": [
                    {"question_id": 102, "question_no": 0, "text": "第二段如何处理？"}
                ]},
            ]
        )
    )
    assert [chunk.content for chunk in payload.chunks] == ["第一段规则", "第二段规则"]
    assert payload.chunks[1].questions[0].question_id == 102
    assert payload.chunks[1].questions[0].text == "第二段如何处理？"


def test_legacy_chunk_without_questions_can_be_reindexed() -> None:
    """迁移期旧知识只有正文分片，也必须能够通过全量索引恢复。"""
    payload = KnowledgePublishRequest.model_validate(
        make_publish_request(
            [{"chunk_no": 0, "content": "历史规则正文", "questions": []}]
        )
    )
    assert payload.chunks[0].content == "历史规则正文"
    assert payload.chunks[0].questions == []


@pytest.mark.parametrize(
    "chunks",
    [
        [{"chunk_no": 1, "content": "编号错误", "questions": [
            {"question_id": 101, "question_no": 0, "text": "怎么处理？"}
        ]}],
        [{"chunk_no": 0, "content": "问法重复", "questions": [
            {"question_id": 101, "question_no": 0, "text": "怎么办？"},
            {"question_id": 102, "question_no": 1, "text": "怎么办？"},
        ]}],
        [{"chunk_no": 0, "content": "空问法", "questions": [
            {"question_id": 101, "question_no": 0, "text": "   "}
        ]}],
        [{"chunk_no": 0, "content": "ID重复", "questions": [
            {"question_id": 101, "question_no": 0, "text": "问法一"},
            {"question_id": 101, "question_no": 1, "text": "问法二"},
        ]}],
        [{"chunk_no": 0, "content": "编号不连续", "questions": [
            {"question_id": 101, "question_no": 1, "text": "问法一"}
        ]}],
    ],
)
def test_invalid_reviewed_chunks_are_rejected(chunks: list[dict[str, object]]) -> None:
    """拒绝无法稳定映射到数据库分片的发布数据。"""
    with pytest.raises(ValidationError):
        KnowledgePublishRequest.model_validate(make_publish_request(chunks))
