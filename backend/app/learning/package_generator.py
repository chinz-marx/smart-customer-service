from __future__ import annotations

import math
import asyncio
import json
import logging
import re
from typing import Any
from typing import Literal

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.prompts.registry import PromptRegistry


logger = logging.getLogger("smart_customer_service.learning.package")
_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class LearningPackageRequest(BaseModel):
    """审核通过的问题资料；标准回答是生成知识和测试集的唯一事实来源。"""

    problem_code: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=1000)
    intent_code: str = Field(min_length=1, max_length=64)
    standard_answer: str = Field(min_length=1, max_length=4000)
    sample_questions: list[str] = Field(min_length=1, max_length=10)
    case_count: int = Field(default=8, ge=8, le=15)


class GeneratedTestCase(BaseModel):
    """前端可编辑的回归用例；预期答案固定为人工审核答案。"""

    question: str
    expected_answer: str
    expected_intent: str
    case_category: Literal[
        "conversational", "omitted", "typo", "inverted", "boundary",
        "hard_negative",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    source_type: Literal["real_user", "llm_generated"]
    expected_match: bool = True


class LearningPackageResponse(BaseModel):
    title: str
    content: str
    tags: list[str]
    standard_questions: list[str]
    test_cases: list[GeneratedTestCase]
    provider: str
    model: str


class _ModelTestCase(BaseModel):
    question: str
    case_category: Literal[
        "conversational", "omitted", "typo", "inverted", "boundary",
        "hard_negative",
    ]
    difficulty: Literal["easy", "medium", "hard"]
    source_type: Literal["real_user", "llm_generated"]
    expected_match: bool


class _ModelPackageResponse(BaseModel):
    title: str
    tags: list[str]
    standard_questions: list[str]
    test_cases: list[_ModelTestCase]


class LearningPackageGenerator:
    """生成知识元数据和测试问法，正文与预期答案始终使用人工审核版本。"""

    def __init__(self, settings: Settings, prompt_registry: PromptRegistry) -> None:
        self.settings = settings
        self.prompt_registry = prompt_registry
        self._llm: ChatOpenAI | None = None

    async def generate(self, payload: LearningPackageRequest) -> LearningPackageResponse:
        if not self.settings.has_real_api_key:
            raise RuntimeError("没有配置可用的知识草稿生成模型")

        context = {
            "problem_code": payload.problem_code,
            "summary": payload.summary.strip(),
            "intent_code": payload.intent_code.strip(),
            "standard_answer": payload.standard_answer.strip(),
            "sample_questions": [value.strip() for value in payload.sample_questions],
            "case_count": payload.case_count,
            # 由程序分配类别配额，模型只负责为每个槽位生成自然问法。
            "required_test_case_slots": self._required_slots(
                payload.case_count, len(set(payload.sample_questions))
            ),
        }
        base_messages = [
            SystemMessage(
                content=self.prompt_registry.get(
                    "smart-customer-learning-package-diverse-system"
                )
            ),
            HumanMessage(
                content=self.prompt_registry.get(
                    "smart-customer-learning-package-diverse-user"
                ).format(
                    package_context=json.dumps(context, ensure_ascii=False)
                )
            ),
        ]

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                messages = list(base_messages)
                if attempt:
                    messages.append(HumanMessage(content=self.prompt_registry.get(
                        "smart-customer-learning-package-diverse-retry"
                    )))
                async with asyncio.timeout(self.settings.learning_package_timeout_seconds):
                    result = await self._get_llm().ainvoke(messages)
                parsed = self._parse(self._message_content_to_text(result.content))
                return self._validate(payload, parsed)
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "知识草稿包生成失败: problem=%s, attempt=%s, error=%s",
                    payload.problem_code,
                    attempt + 1,
                    type(exc).__name__,
                )
        raise ValueError("模型未能返回符合要求的知识草稿和测试问法") from last_error

    def _validate(
        self,
        request: LearningPackageRequest,
        response: _ModelPackageResponse,
    ) -> LearningPackageResponse:
        title = response.title.strip()
        tags = list(dict.fromkeys(tag.strip() for tag in response.tags if tag.strip()))
        standard_questions = [value.strip() for value in response.standard_questions]
        test_cases = response.test_cases
        if not title or len(title) > 80 or not 1 <= len(tags) <= 5:
            raise ValueError("标题或标签不符合要求")
        if len(standard_questions) != 3 or len(test_cases) != request.case_count:
            raise ValueError("标准问法或测试问法数量不正确")
        normalized = [
            self._normalize(value) for value in standard_questions
        ] + [self._normalize(item.question) for item in test_cases]
        if any(not value for value in normalized) or len(normalized) != len(set(normalized)):
            raise ValueError("模型返回了空问法或重复问法")
        self._validate_diversity(request, test_cases)

        answer = request.standard_answer.strip()
        intent = request.intent_code.strip()
        return LearningPackageResponse(
            title=title,
            content=answer,
            tags=tags,
            standard_questions=standard_questions,
            test_cases=[
                GeneratedTestCase(
                    question=item.question.strip(),
                    expected_answer=answer,
                    expected_intent=intent,
                    case_category=item.case_category,
                    difficulty=item.difficulty,
                    source_type=item.source_type,
                    expected_match=item.expected_match,
                )
                for item in test_cases
            ],
            provider="doubao",
            model=self.settings.doubao_model,
        )

    @staticmethod
    def _required_slots(case_count: int, real_sample_count: int = 0) -> list[dict[str, Any]]:
        """生成固定配额；增加用例时优先扩充困难和边界表达。"""
        base = [
            ("conversational", "easy", True),
            ("omitted", "medium", True),
            ("typo", "medium", True),
            ("inverted", "medium", True),
            ("boundary", "hard", True),
        ]
        negative_count = math.ceil(case_count * 0.2)
        extra_positive = case_count - len(base) - negative_count
        extras = [
            ("conversational", "medium", True),
            ("boundary", "hard", True),
            ("omitted", "hard", True),
            ("inverted", "hard", True),
            ("typo", "hard", True),
            ("conversational", "hard", True),
            ("boundary", "medium", True),
        ]
        slots = base + extras[:extra_positive]
        slots.extend(("hard_negative", "hard", False) for _ in range(negative_count))
        result = [
            {
                "case_category": category,
                "difficulty": difficulty,
                "expected_match": expected,
                "source_type": "llm_generated",
            }
            for category, difficulty, expected in slots
        ]
        # 最多保留30%的真实问法；真实样本不足时不伪造数量。
        real_quota = min(real_sample_count, math.ceil(case_count * 0.3))
        for item in [value for value in result if value["expected_match"]][:real_quota]:
            item["source_type"] = "real_user"
        return result

    def _validate_diversity(
        self,
        request: LearningPackageRequest,
        cases: list[_ModelTestCase],
    ) -> None:
        """把多元性变成代码门槛，避免模型只输出一组同义改写。"""
        categories = {item.case_category for item in cases if item.expected_match}
        required = {"conversational", "omitted", "typo", "inverted", "boundary"}
        if not required.issubset(categories):
            raise ValueError("正样本未覆盖全部多元表达类别")
        negative_count = sum(
            item.case_category == "hard_negative" and not item.expected_match
            for item in cases
        )
        if negative_count < math.ceil(request.case_count * 0.2):
            raise ValueError("困难负样本占比低于20%")
        expected_slots = [
            (
                item["case_category"], item["difficulty"], item["expected_match"],
                item["source_type"],
            )
            for item in self._required_slots(
                request.case_count, len(set(request.sample_questions))
            )
        ]
        actual_slots = [
            (
                item.case_category, item.difficulty, item.expected_match,
                item.source_type,
            ) for item in cases
        ]
        if actual_slots != expected_slots:
            raise ValueError("测试用例没有按照程序分配的多元槽位顺序返回")
        for item in cases:
            if item.case_category == "hard_negative":
                if item.expected_match or item.difficulty != "hard":
                    raise ValueError("困难负样本标记不一致")
            elif not item.expected_match:
                raise ValueError("只有困难负样本允许expected_match=false")
            if item.source_type == "real_user" and item.question.strip() not in {
                value.strip() for value in request.sample_questions
            }:
                raise ValueError("real_user用例必须来自真实样本")

    def _get_llm(self) -> ChatOpenAI:
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self.settings.doubao_api_key,
                base_url=self.settings.doubao_base_url,
                model=self.settings.doubao_model,
                temperature=self.settings.learning_package_temperature,
                timeout=self.settings.learning_package_timeout_seconds,
                max_retries=self.settings.doubao_max_retries,
                max_tokens=1800,
            )
        return self._llm

    def _parse(self, content: str) -> _ModelPackageResponse:
        cleaned = _JSON_FENCE.sub("", content.strip())
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型响应中没有JSON对象")
        return _ModelPackageResponse.model_validate_json(cleaned[start : end + 1])

    @staticmethod
    def _normalize(value: str) -> str:
        return re.sub(r"[\s？?。！!]+$", "", value.strip()).casefold()

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict)
            )
        return str(content)


def create_learning_package_router(
    settings: Settings,
    prompt_registry: PromptRegistry,
) -> APIRouter:
    router = APIRouter(prefix="/api/learning/packages", tags=["learning-packages"])
    generator = LearningPackageGenerator(settings, prompt_registry)

    @router.post("/generate", response_model=LearningPackageResponse)
    async def generate_package(payload: LearningPackageRequest) -> LearningPackageResponse:
        try:
            return await generator.generate(payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("知识草稿与测试集生成失败: problem=%s", payload.problem_code)
            raise HTTPException(status_code=502, detail="知识草稿生成暂时失败，请稍后重试") from exc

    return router
