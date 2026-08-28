from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field, model_validator

from app.config import Settings
from app.prompts.registry import PromptRegistry


logger = logging.getLogger("smart_customer_service.knowledge_questions")
_JSON_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


class QuestionChunkInput(BaseModel):
    """一个需要生成标准问法的原子分片。"""

    chunk_no: int = Field(ge=0)
    content: str = Field(min_length=1, max_length=4000)
    excluded_questions: list[str] = Field(default_factory=list, max_length=8)


class QuestionGenerationRequest(BaseModel):
    """前端批量生成标准问法的请求。"""

    title: str = Field(default="", max_length=256)
    question_count: int = Field(default=3, ge=1, le=8)
    chunks: list[QuestionChunkInput] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def validate_chunks(self) -> "QuestionGenerationRequest":
        """拒绝重复编号和只有空白字符的内容。"""
        chunk_numbers = [chunk.chunk_no for chunk in self.chunks]
        if len(chunk_numbers) != len(set(chunk_numbers)):
            raise ValueError("chunk_no不能重复")
        if any(not chunk.content.strip() for chunk in self.chunks):
            raise ValueError("原子分片内容不能为空")
        return self


class GeneratedQuestionChunk(BaseModel):
    """模型为一个分片生成的问法集合。"""

    chunk_no: int
    questions: list[str]


class QuestionGenerationResponse(BaseModel):
    """返回前端的结构化问法生成结果。"""

    provider: str
    model: str
    chunks: list[GeneratedQuestionChunk]


class _ModelQuestionResponse(BaseModel):
    """LLM必须遵循的JSON响应结构。"""

    chunks: list[GeneratedQuestionChunk]


class KnowledgeQuestionGenerator:
    """使用现有豆包回答模型生成知识库标准问法。

    该服务只生成候选问法，不直接写数据库。用户仍需在页面检查、修改并提交审批，
    因此模型输出不会绕过现有知识审核流程。
    """

    def __init__(
        self,
        settings: Settings,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.prompt_registry = prompt_registry or PromptRegistry(settings, None)
        self._llm: ChatOpenAI | None = None

    async def generate(
        self, payload: QuestionGenerationRequest
    ) -> QuestionGenerationResponse:
        """调用LLM并严格校验分片编号、数量、重复项和排除项。"""
        if not self.settings.has_real_api_key:
            raise RuntimeError("没有配置可用的知识问法生成模型")

        model_input = {
            "title": payload.title.strip(),
            "question_count": payload.question_count,
            "chunks": [
                {
                    "chunk_no": chunk.chunk_no,
                    "content": chunk.content.strip(),
                    "excluded_questions": [
                        question.strip()
                        for question in chunk.excluded_questions
                        if question.strip()
                    ],
                }
                for chunk in payload.chunks
            ],
        }
        messages = [
            SystemMessage(
                content=self.prompt_registry.get(
                    "smart-customer-question-generation-system"
                )
            ),
            HumanMessage(
                content=self.prompt_registry.get(
                    "smart-customer-question-generation-user"
                ).format(model_input=json.dumps(model_input, ensure_ascii=False))
            ),
        ]

        last_error: Exception | None = None
        for attempt in range(2):
            try:
                # 第二次调用明确提醒模型修复格式，避免偶发Markdown或数量错误。
                current_messages = list(messages)
                if attempt:
                    current_messages.append(
                        HumanMessage(
                            content=self.prompt_registry.get(
                                "smart-customer-question-generation-retry"
                            )
                        )
                    )
                async with asyncio.timeout(
                    self.settings.knowledge_question_timeout_seconds
                ):
                    result = await self._get_llm().ainvoke(current_messages)
                parsed = self._parse_model_response(
                    self._message_content_to_text(result.content)
                )
                validated = self._validate_result(payload, parsed)
                return QuestionGenerationResponse(
                    provider="doubao",
                    model=self.settings.effective_knowledge_question_model,
                    chunks=validated,
                )
            except Exception as exc:
                last_error = exc
                logger.warning(
                    "知识标准问法生成失败: attempt=%s, error=%s",
                    attempt + 1,
                    type(exc).__name__,
                )
        raise ValueError("模型未能返回符合要求的标准问法") from last_error

    def _get_llm(self) -> ChatOpenAI:
        """延迟创建模型客户端，连续生成时复用HTTP连接池。"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self.settings.doubao_api_key,
                base_url=self.settings.doubao_base_url,
                model=self.settings.effective_knowledge_question_model,
                temperature=self.settings.knowledge_question_temperature,
                timeout=self.settings.knowledge_question_timeout_seconds,
                max_retries=self.settings.doubao_max_retries,
                max_tokens=2000,
            )
        return self._llm

    def _parse_model_response(self, text: str) -> _ModelQuestionResponse:
        """从模型文本中提取JSON，并交给Pydantic检查基本结构。"""
        cleaned = _JSON_FENCE.sub("", text.strip())
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型响应中没有JSON对象")
        payload = json.loads(cleaned[start : end + 1])
        return _ModelQuestionResponse.model_validate(payload)

    def _validate_result(
        self,
        request: QuestionGenerationRequest,
        response: _ModelQuestionResponse,
    ) -> list[GeneratedQuestionChunk]:
        """检查模型没有漏分片、串分片、少问法或返回旧问法。"""
        expected = {chunk.chunk_no: chunk for chunk in request.chunks}
        actual = {chunk.chunk_no: chunk for chunk in response.chunks}
        if set(actual) != set(expected) or len(actual) != len(response.chunks):
            raise ValueError("模型返回的分片编号不完整或重复")

        result: list[GeneratedQuestionChunk] = []
        for request_chunk in request.chunks:
            generated = actual[request_chunk.chunk_no]
            questions = [question.strip() for question in generated.questions]
            if len(questions) != request.question_count or any(
                not question for question in questions
            ):
                raise ValueError("模型返回的问法数量不正确或包含空问法")

            normalized = [self._normalize_question(question) for question in questions]
            excluded = {
                self._normalize_question(question)
                for question in request_chunk.excluded_questions
                if question.strip()
            }
            if len(normalized) != len(set(normalized)):
                raise ValueError("模型返回了重复问法")
            if excluded.intersection(normalized):
                raise ValueError("模型重新生成时返回了需要排除的旧问法")
            result.append(
                GeneratedQuestionChunk(
                    chunk_no=request_chunk.chunk_no,
                    questions=questions,
                )
            )
        return result

    @staticmethod
    def _normalize_question(value: str) -> str:
        """忽略空格和末尾标点比较问法，防止表面不同的重复项。"""
        return re.sub(r"[\s？?。！!]+$", "", value.strip()).casefold()

    @staticmethod
    def _message_content_to_text(content: Any) -> str:
        """兼容LangChain返回字符串或多模态文本块。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            return "".join(
                str(block.get("text", ""))
                for block in content
                if isinstance(block, dict)
            )
        return str(content)


def create_question_generation_router(
    settings: Settings,
    prompt_registry: PromptRegistry | None = None,
) -> APIRouter:
    """创建供知识管理页面使用的LLM问法生成接口。"""
    router = APIRouter(prefix="/api/knowledge/questions", tags=["knowledge-questions"])
    generator = KnowledgeQuestionGenerator(settings, prompt_registry)

    @router.post("/generate", response_model=QuestionGenerationResponse)
    async def generate_questions(
        payload: QuestionGenerationRequest,
        request: Request,
    ) -> QuestionGenerationResponse:
        # request参数保留给后续登录态、审计日志和限流使用。
        del request
        try:
            return await generator.generate(payload)
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        except Exception as exc:
            logger.exception("知识标准问法接口调用失败")
            raise HTTPException(
                status_code=502,
                detail="标准问法生成暂时失败，请稍后重试",
            ) from exc

    return router
