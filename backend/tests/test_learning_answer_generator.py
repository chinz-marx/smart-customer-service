import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.learning.answer_generator import LearningAnswerGenerator, LearningAnswerRequest
from app.prompts.registry import PromptRegistry


class FakeAnswerLlm:
    """返回固定标准回答，单元测试不访问真实模型。"""

    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    async def ainvoke(self, _messages: object) -> SimpleNamespace:
        self.calls += 1
        return SimpleNamespace(content=self.answer)


def make_generator(answer: str) -> tuple[LearningAnswerGenerator, FakeAnswerLlm]:
    settings = Settings(
        doubao_api_key="test-api-key",
        doubao_model="test-answer-model",
        learning_answer_timeout_seconds=1,
    )
    generator = LearningAnswerGenerator(settings, PromptRegistry(settings, None))
    llm = FakeAnswerLlm(answer)
    generator._llm = llm
    return generator, llm


def make_request() -> LearningAnswerRequest:
    return LearningAnswerRequest(
        problem_code="PB-TEST-001",
        summary="退款已成功但银行卡没有到账",
        intent_code="refund_query",
        source_names=["没帮助"],
        sample_questions=["退款三天了银行卡怎么还没有收到？"],
        previous_answers=["请稍后查看"],
    )


def test_learning_answer_returns_review_draft() -> None:
    generator, llm = make_generator("退款到账时间取决于原支付渠道，请先查询退款进度。")

    result = asyncio.run(generator.generate(make_request()))

    assert result.answer.startswith("退款到账时间")
    assert result.provider == "doubao"
    assert result.model == "test-answer-model"
    assert llm.calls == 1


def test_learning_answer_rejects_empty_model_output() -> None:
    generator, _ = make_generator("   ")

    with pytest.raises(ValueError, match="为空或过长"):
        asyncio.run(generator.generate(make_request()))
