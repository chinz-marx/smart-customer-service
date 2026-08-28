from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, HTTPException
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.config import Settings
from app.prompts.registry import PromptRegistry


logger = logging.getLogger("smart_customer_service.learning.answer")


class LearningAnswerRequest(BaseModel):
    """Java问题审核页传入的有限上下文，不允许把整段会话无限交给模型。"""

    problem_code: str = Field(min_length=1, max_length=64)
    summary: str = Field(min_length=1, max_length=1000)
    intent_code: str | None = Field(default=None, max_length=64)
    source_names: list[str] = Field(default_factory=list, max_length=6)
    sample_questions: list[str] = Field(min_length=1, max_length=10)
    previous_answers: list[str] = Field(default_factory=list, max_length=5)


class LearningAnswerResponse(BaseModel):
    """返回候选回答及模型信息，Java会连同审核记录一起保存。"""

    answer: str
    provider: str
    model: str


class LearningAnswerGenerator:
    """为问题簇生成标准回答草稿；生成结果必须经过Java审核接口确认。"""

    def __init__(self, settings: Settings, prompt_registry: PromptRegistry) -> None:
        self.settings = settings
        self.prompt_registry = prompt_registry
        self._llm: ChatOpenAI | None = None

    async def generate(self, payload: LearningAnswerRequest) -> LearningAnswerResponse:
        if not self.settings.has_real_api_key:
            raise RuntimeError("没有配置可用的标准回答生成模型")

        context = {
            "problem_code": payload.problem_code,
            "summary": payload.summary.strip(),
            "intent_code": payload.intent_code,
            "source_names": payload.source_names,
            "sample_questions": [value.strip() for value in payload.sample_questions],
            "previous_answers": [value.strip() for value in payload.previous_answers if value.strip()],
        }
        messages = [
            SystemMessage(
                content=self.prompt_registry.get("smart-customer-learning-answer-system")
            ),
            HumanMessage(
                content=self.prompt_registry.get("smart-customer-learning-answer-user").format(
                    problem_context=json.dumps(context, ensure_ascii=False)
                )
            ),
        ]
        async with asyncio.timeout(self.settings.learning_answer_timeout_seconds):
            result = await self._get_llm().ainvoke(messages)
        answer = self._message_content_to_text(result.content).strip()
        if not answer or len(answer) > 4000:
            raise ValueError("模型返回的标准回答为空或过长")
        return LearningAnswerResponse(
            answer=answer,
            provider="doubao",
            model=self.settings.doubao_model,
        )

    def _get_llm(self) -> ChatOpenAI:
        """延迟创建客户端，让应用启动不依赖模型网络，同时复用后续HTTP连接。"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self.settings.doubao_api_key,
                base_url=self.settings.doubao_base_url,
                model=self.settings.doubao_model,
                temperature=self.settings.learning_answer_temperature,
                timeout=self.settings.learning_answer_timeout_seconds,
                max_retries=self.settings.doubao_max_retries,
                max_tokens=1200,
            )
        return self._llm

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


def create_learning_answer_router(
    settings: Settings,
    prompt_registry: PromptRegistry,
) -> APIRouter:
    """创建问题审核页使用的LLM标准回答生成接口。"""
    router = APIRouter(prefix="/api/learning/answers", tags=["learning-answers"])
    generator = LearningAnswerGenerator(settings, prompt_registry)

    @router.post("/generate", response_model=LearningAnswerResponse)
    async def generate_answer(payload: LearningAnswerRequest) -> LearningAnswerResponse:
        try:
            return await generator.generate(payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("问题标准回答生成失败: problem_code=%s", payload.problem_code)
            raise HTTPException(status_code=502, detail="标准回答生成暂时失败，请稍后重试") from exc

    return router
