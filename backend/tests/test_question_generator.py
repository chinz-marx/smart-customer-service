import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.retrieval.question_generator import (
    KnowledgeQuestionGenerator,
    QuestionGenerationRequest,
)


class FakeQuestionLlm:
    """按顺序返回预设文本，模拟真实LangChain模型客户端。"""

    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    async def ainvoke(self, _messages: object) -> SimpleNamespace:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return SimpleNamespace(content=response)


def make_request(
    excluded_questions: list[str] | None = None,
) -> QuestionGenerationRequest:
    """构造一个最小批量生成请求。"""
    return QuestionGenerationRequest(
        title="积分有效期",
        question_count=3,
        chunks=[
            {
                "chunk_no": 0,
                "content": "普通积分自到账之日起十二个月内有效，过期后自动失效。",
                "excluded_questions": excluded_questions or [],
            }
        ],
    )


def make_generator(responses: list[str]) -> tuple[KnowledgeQuestionGenerator, FakeQuestionLlm]:
    """创建使用假模型的生成器，避免单元测试访问外部网络。"""
    generator = KnowledgeQuestionGenerator(
        Settings(
            doubao_api_key="test-api-key",
            doubao_model="test-model",
            knowledge_question_timeout_seconds=1,
        )
    )
    llm = FakeQuestionLlm(responses)
    generator._llm = llm  # 测试替换惰性模型客户端。
    return generator, llm


def test_generate_returns_structured_questions() -> None:
    generator, llm = make_generator(
        [
            '{"chunks":[{"chunk_no":0,"questions":'
            '["积分多久过期？","积分有效期是一年吗？","积分到期后还能用吗？"]}]}'
        ]
    )
    result = asyncio.run(generator.generate(make_request()))
    assert result.provider == "doubao"
    assert result.model == "test-model"
    assert len(result.chunks[0].questions) == 3
    assert llm.calls == 1


def test_invalid_json_is_retried_once() -> None:
    generator, llm = make_generator(
        [
            "这不是JSON",
            '{"chunks":[{"chunk_no":0,"questions":'
            '["积分多久失效？","积分能保留几年？","过期积分还能恢复吗？"]}]}',
        ]
    )
    result = asyncio.run(generator.generate(make_request()))
    assert result.chunks[0].questions[0] == "积分多久失效？"
    assert llm.calls == 2


def test_regeneration_rejects_old_questions() -> None:
    old_question = "积分多久过期？"
    response = (
        '{"chunks":[{"chunk_no":0,"questions":'
        f'["{old_question}","积分有效期是一年吗？","积分到期后还能用吗？"]}}]}}'
    )
    generator, llm = make_generator([response])
    with pytest.raises(ValueError, match="符合要求"):
        asyncio.run(generator.generate(make_request([old_question])))
    assert llm.calls == 2
