import asyncio
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.learning.package_generator import LearningPackageGenerator, LearningPackageRequest
from app.prompts.registry import PromptRegistry


class FakePackageLlm:
    def __init__(self, responses: list[str]) -> None:
        self.responses = responses
        self.calls = 0

    async def ainvoke(self, _messages: object) -> SimpleNamespace:
        response = self.responses[min(self.calls, len(self.responses) - 1)]
        self.calls += 1
        return SimpleNamespace(content=response)


def request() -> LearningPackageRequest:
    return LearningPackageRequest(
        problem_code="PB-001",
        summary="退款到账延迟",
        intent_code="refund_query",
        standard_answer="退款审核通过后会原路退回，到账时间取决于支付机构。",
        sample_questions=["退款怎么还没到？"],
        case_count=8,
    )


def generator(responses: list[str]) -> tuple[LearningPackageGenerator, FakePackageLlm]:
    settings = Settings(doubao_api_key="test-key", doubao_model="test-model")
    value = LearningPackageGenerator(settings, PromptRegistry(settings, None))
    llm = FakePackageLlm(responses)
    value._llm = llm
    return value, llm


def test_package_uses_approved_answer_for_all_cases() -> None:
    raw = (
        '{"title":"退款到账时间说明","tags":["退款","到账"],'
        '"standard_questions":["退款多久到？","退款退到哪里？","退款到账时间多长？"],'
        '"test_cases":['
        '{"question":"退款怎么还没到？","case_category":"conversational","difficulty":"easy","source_type":"real_user","expected_match":true},'
        '{"question":"还没到咋办","case_category":"omitted","difficulty":"medium","source_type":"llm_generated","expected_match":true},'
        '{"question":"退款到帐要多久？","case_category":"typo","difficulty":"medium","source_type":"llm_generated","expected_match":true},'
        '{"question":"审核过了，几天能到账？","case_category":"inverted","difficulty":"medium","source_type":"llm_generated","expected_match":true},'
        '{"question":"原路退回后银行卡多久显示？","case_category":"boundary","difficulty":"hard","source_type":"llm_generated","expected_match":true},'
        '{"question":"钱咋还没来？","case_category":"conversational","difficulty":"medium","source_type":"llm_generated","expected_match":true},'
        '{"question":"退款审核失败怎么重新申请？","case_category":"hard_negative","difficulty":"hard","source_type":"llm_generated","expected_match":false},'
        '{"question":"退货运费由谁承担？","case_category":"hard_negative","difficulty":"hard","source_type":"llm_generated","expected_match":false}]}'
    )
    service, llm = generator([raw])

    result = asyncio.run(service.generate(request()))

    assert result.content == request().standard_answer
    assert len(result.test_cases) == 8
    assert all(case.expected_answer == request().standard_answer for case in result.test_cases)
    assert llm.calls == 1


def test_package_retries_duplicate_questions_then_fails() -> None:
    raw = (
        '{"title":"退款到账","tags":["退款"],'
        '"standard_questions":["退款多久到？","退款多久到？","退款到哪？"],'
        '"test_cases":[]}'
    )
    service, llm = generator([raw])

    with pytest.raises(ValueError, match="符合要求"):
        asyncio.run(service.generate(request()))
    assert llm.calls == 2
