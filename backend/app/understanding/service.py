from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import ValidationError

from app.config import Settings
from app.configs.loader import load_runtime_config
from app.errors import safe_error_message
from app.intent.classifier import IntentClassifier
from app.prompts.registry import PromptRegistry
from app.schemas import ChatHistoryItem
from app.tools.mcp_client import McpToolClient
from app.understanding.prompt import SYSTEM_ROUTE_CODES, build_user_payload
from app.understanding.schemas import UnderstandingResult


class UnderstandingService:
    """统一的用户语义理解服务。

    hybrid模式优先调用LLM；模型不可用或输出不合法时，自动使用现有关键词分类器。
    这样可以逐步切换架构，而不让模型故障中断整条客服链路。
    """

    def __init__(
        self,
        settings: Settings,
        fallback_classifier: IntentClassifier | None = None,
        prompt_registry: PromptRegistry | None = None,
        mcp_tool_client: McpToolClient | None = None,
    ) -> None:
        self.settings = settings
        self.fallback_classifier = fallback_classifier or IntentClassifier()
        self.prompt_registry = prompt_registry or PromptRegistry(settings, None)
        self.mcp_tool_client = mcp_tool_client
        # 一个服务实例复用同一个LangChain客户端，复用HTTP连接并减少握手开销。
        self._llm: ChatOpenAI | None = None

    async def understand(
        self,
        message: str,
        history: list[ChatHistoryItem],
        current_intent: str | None,
        current_slots: dict[str, str],
        current_tool: str | None = None,
    ) -> UnderstandingResult:
        """识别意图、语义槽位、情绪和风险。

        keyword模式完全不请求模型；hybrid模式在没有真实Key时也会直接走关键词，
        因此现有本地开发和自动测试不会产生模型费用。
        """
        if self.settings.understanding_mode == "keyword":
            return self._keyword_fallback(
                message,
                current_intent=current_intent,
                current_tool=current_tool,
            )

        if not self.settings.has_real_understanding_api_key:
            if self.settings.understanding_mode == "hybrid":
                return self._keyword_fallback(
                    message,
                    error_message="未配置真实模型Key",
                    current_intent=current_intent,
                    current_tool=current_tool,
                )
            return self._llm_error_result("未配置真实模型Key")

        try:
            # asyncio.timeout是Python 3.11+标准能力，Windows和Linux行为一致。
            async with asyncio.timeout(self.settings.understanding_timeout_seconds):
                raw_content = await self._invoke_llm(
                    message=message,
                    history=history,
                    current_intent=current_intent,
                    current_slots=current_slots,
                    current_tool=current_tool,
                )
            result = self._parse_result(raw_content)
            # 小模型偶尔会在明确的追加诉求中只保留Tool。这里不按业务关键词做路由，
            # 只识别通用连接结构并把追加子句交给Redis Search继续验证；知识未命中时
            # 编排器仍会直接返回Tool结果，不会凭这条保护规则生成答案。
            result = self._protect_composite_plan(result, message)
            # 明确意图不能因为缺少业务槽位进入通用澄清；参数完整性由SlotManager负责。
            if (
                result.intent != "unknown"
                and result.confidence >= self.settings.understanding_confidence_threshold
                and result.needs_clarification
            ):
                result = result.model_copy(update={"needs_clarification": False})
            if (
                self.settings.understanding_mode == "hybrid"
                and (
                    result.intent == "unknown"
                    or result.confidence < self.settings.understanding_confidence_threshold
                )
            ):
                # 模型请求成功不代表判断一定可靠。unknown或低置信度时让关键词分类器复核，
                # 只有关键词给出更明确且置信度更高的结果才替换，避免错误执行Tool。
                fallback = self._keyword_fallback(
                    message,
                    error_message="LLM返回未知意图或置信度不足，已使用关键词复核",
                    current_intent=current_intent,
                    current_tool=current_tool,
                )
                if fallback.intent != "unknown" and fallback.confidence > result.confidence:
                    return fallback
            return result
        except Exception as exc:
            error_message = safe_error_message(exc)
            if self.settings.understanding_mode == "hybrid":
                return self._keyword_fallback(
                    message,
                    error_message=error_message,
                    current_intent=current_intent,
                    current_tool=current_tool,
                )
            return self._llm_error_result(error_message)

    async def understand_pending_tool(
        self,
        message: str,
        history: list[ChatHistoryItem],
        current_intent: str | None,
        current_slots: dict[str, str],
        current_tool: str,
    ) -> UnderstandingResult | None:
        """只发送当前 Tool Schema，判断本轮是续填参数还是需要重新路由。

        返回 None 表示用户可能切换了业务，由调用方继续执行完整意图识别。模型不可用
        时同样返回 None，让现有 keyword/hybrid 降级链路接管。
        """
        if (
            self.settings.understanding_mode == "keyword"
            or not self.settings.has_real_understanding_api_key
            or self.mcp_tool_client is None
        ):
            return None
        definition = self.mcp_tool_client.get_tool(current_tool)
        if definition is None:
            return None

        try:
            async with asyncio.timeout(self.settings.understanding_timeout_seconds):
                raw_content = await self._invoke_llm(
                    message=message,
                    history=history,
                    current_intent=current_intent,
                    current_slots=current_slots,
                    current_tool=current_tool,
                    available_tools_override=[definition.prompt_payload()],
                )
            result = self._parse_result(raw_content)
        except Exception:
            return None

        if result.tool_name == current_tool and result.route_type in {"tool", "composite"}:
            return result
        return None

    async def _invoke_llm(
        self,
        message: str,
        history: list[ChatHistoryItem],
        current_intent: str | None,
        current_slots: dict[str, str],
        current_tool: str | None = None,
        available_tools_override: list[dict[str, Any]] | None = None,
    ) -> str:
        """调用OpenAI兼容模型并返回纯文本内容。

        这里没有依赖供应商专有的JSON Schema参数，避免豆包兼容接口不支持时调用失败；
        返回内容仍会在_parse_result中经过严格JSON解析和Pydantic校验。
        """
        runtime_config = load_runtime_config()
        # Redis Search 只提供候选 Tool，最终选择、参数提取和组合检索判断仍由 LLM 完成。
        available_tools = available_tools_override
        if available_tools is None:
            available_tools = (
                await self.mcp_tool_client.candidate_catalog(message, current_tool)
                if self.mcp_tool_client is not None
                else []
            )
        llm = self._get_llm()
        result = await llm.ainvoke(
            [
                SystemMessage(
                    content=self.prompt_registry.get(
                        "smart-customer-understanding-system"
                    )
                ),
                HumanMessage(
                    content=build_user_payload(
                        message=message,
                        history=history,
                        current_intent=current_intent,
                        current_slots=current_slots,
                        runtime_config=runtime_config,
                        available_tools=available_tools,
                        current_tool=current_tool,
                    )
                ),
            ]
        )
        return self._message_content_to_text(result.content)

    def _get_llm(self) -> ChatOpenAI:
        """延迟创建并复用模型客户端，避免每轮会话重复建立HTTP连接。"""
        if self._llm is None:
            self._llm = ChatOpenAI(
                api_key=self.settings.understanding_api_key,
                base_url=self.settings.understanding_base_url,
                model=self.settings.effective_understanding_model,
                temperature=self.settings.understanding_temperature,
                timeout=self.settings.understanding_timeout_seconds,
                max_retries=self.settings.doubao_max_retries,
            )
        return self._llm

    def _parse_result(self, content: str) -> UnderstandingResult:
        """从模型文本中提取JSON并校验意图编码。

        部分兼容模型偶尔会包一层```json代码块，所以先定位首尾花括号；
        但不会尝试修复错误JSON，错误内容应进入可观测的兜底分支。
        """
        start = content.find("{")
        end = content.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("模型没有返回JSON对象")

        try:
            payload = json.loads(content[start : end + 1])
            result = UnderstandingResult.model_validate(payload)
        except (json.JSONDecodeError, ValidationError) as exc:
            raise ValueError(f"模型结构化输出校验失败：{safe_error_message(exc)}") from exc

        # 新版业务意图直接使用Java MCP Tool名称；knowledge_query表示纯知识检索。
        # YAML业务意图仍加入兼容集合，使旧Nacos Prompt可以平滑过渡而不阻断请求。
        allowed_intents = set(load_runtime_config().intents)
        allowed_intents.update(SYSTEM_ROUTE_CODES)
        allowed_intents.update({"knowledge_query", "unknown"})
        intent_is_registered_tool = bool(
            self.mcp_tool_client is not None
            and self.mcp_tool_client.get_tool(result.intent) is not None
        )
        if result.intent not in allowed_intents and not intent_is_registered_tool:
            raise ValueError(f"模型返回了未配置的意图：{result.intent}")

        # 两个数据来源先独立归一化，再生成唯一执行计划。旧提示词只返回route_type时，
        # 这里也会反向补齐布尔值，因此Nacos回滚旧版本不会破坏兼容性。
        requires_tool = result.requires_tool or result.route_type in {"tool", "composite"}
        requires_knowledge = (
            result.requires_knowledge or result.route_type in {"knowledge", "composite"}
        )

        # 小模型偶尔会返回相互矛盾的字段：intent已经精确选中一个
        # Java MCP Tool，却因为缺少业务参数把route_type标成unknown/legacy，
        # 并要求通用澄清。Tool是实际注册目录中的精确名称，因此这里可以
        # 做通用的结构修复；缺少哪些参数仍由MCP Schema决定，不写任何业务关键词。
        if intent_is_registered_tool:
            if result.tool_name and result.tool_name != result.intent:
                raise ValueError(
                    f"模型返回的意图与MCP工具冲突：{result.intent} != {result.tool_name}"
                )
            requires_tool = True
            result = result.model_copy(
                update={
                    "tool_name": result.intent,
                    "needs_clarification": False,
                }
            )

        if requires_tool and requires_knowledge:
            route_type = "composite"
        elif requires_tool:
            route_type = "tool"
        elif requires_knowledge:
            route_type = "knowledge"
        else:
            route_type = result.route_type
        result = result.model_copy(
            update={
                "requires_tool": requires_tool,
                "requires_knowledge": requires_knowledge,
                "route_type": route_type,
            }
        )
        if result.tool_name:
            definition = (
                self.mcp_tool_client.get_tool(result.tool_name)
                if self.mcp_tool_client is not None
                else None
            )
            if definition is None:
                raise ValueError(f"模型返回了未注册的MCP工具：{result.tool_name}")
        if result.route_type in {"tool", "composite"} and not result.tool_name:
            raise ValueError("模型选择了Tool执行计划但没有返回tool_name")

        # tool_name来自Java实际注册目录，因此比旧YAML意图编码更可靠。统一使用它作为
        # 业务意图后，状态、日志和评测不会同时保存两套可能冲突的业务编码。
        if result.route_type in {"tool", "composite"} and result.tool_name:
            result = result.model_copy(update={"intent": result.tool_name})
        elif result.route_type == "knowledge" and result.intent not in SYSTEM_ROUTE_CODES:
            result = result.model_copy(update={"intent": "knowledge_query"})
        return result.model_copy(update={"source": "llm", "error_message": None})

    def _keyword_fallback(
        self,
        message: str,
        error_message: str | None = None,
        current_intent: str | None = None,
        current_tool: str | None = None,
    ) -> UnderstandingResult:
        """把关键词结果包装成统一结构，并保护多轮纯槽位输入。"""
        if current_intent and self._is_structured_slot_followup(message):
            # 新版业务会话以active_tool为准。模型超时时，用户只补订单号等参数仍应
            # 继续当前MCP Tool，不能退回YAML legacy路径或丢失多轮状态。
            if current_tool:
                return UnderstandingResult(
                    intent=current_tool,
                    confidence=0.88,
                    slots={},
                    needs_clarification=False,
                    requires_tool=True,
                    route_type="tool",
                    tool_name=current_tool,
                    source="keyword",
                    error_message=error_message,
                )
            return UnderstandingResult(
                intent=current_intent,
                confidence=0.88,
                slots={},
                needs_clarification=False,
                source="keyword",
                error_message=error_message,
            )

        intent = self.fallback_classifier.classify(message)
        # hybrid复核可能从兼容的intents.yaml得到与Java MCP完全相同的
        # Tool名称。此时YAML只负责故障复核，执行计划和参数定义仍必须
        # 切换到真实MCP Schema，否则0.65~0.85的结果会误进入通用确认话术。
        registered_tool = (
            self.mcp_tool_client.get_tool(intent.intent)
            if self.mcp_tool_client is not None
            else None
        )
        if registered_tool is not None:
            return UnderstandingResult(
                intent=intent.intent,
                confidence=intent.confidence,
                slots={},
                needs_clarification=False,
                requires_tool=True,
                route_type="tool",
                tool_name=intent.intent,
                source="keyword",
                error_message=error_message,
            )
        return UnderstandingResult(
            intent=intent.intent,
            confidence=intent.confidence,
            slots={},
            needs_clarification=intent.intent == "unknown",
            source="keyword",
            error_message=error_message,
        )

    def _protect_composite_plan(
        self,
        result: UnderstandingResult,
        message: str,
    ) -> UnderstandingResult:
        """为Tool后的明确追加诉求补一个知识检索候选，不替代LLM意图判断。"""
        if not result.requires_tool or result.requires_knowledge:
            return result

        # 这些词只表示“后面还有一个诉求”，不携带订单、退款等任何业务语义。
        connector_pattern = re.compile(
            r"(?:同时(?:我)?还(?:想|要)?|另外|此外|顺便|并且|以及|还想|还要)"
        )
        matches = list(connector_pattern.finditer(message))
        if not matches:
            return result

        additional_query = message[matches[-1].end() :].strip(" ，,。；;：:!?！？")
        if len(additional_query) < 4:
            return result
        return result.model_copy(
            update={
                "requires_knowledge": True,
                "route_type": "composite",
                "knowledge_query": additional_query,
            }
        )

    def _is_structured_slot_followup(self, message: str) -> bool:
        """判断本轮是否只是在补充订单号或手机号尾号，而不是提出新诉求。"""
        patterns = (
            r"(?:订单号|订单|单号)\s*(?:是|为|[:：])?\s*[A-Za-z0-9_-]{6,64}[。.!！]?",
            r"(?:手机号后四位|手机尾号|尾号)\s*(?:是|为|[:：])?\s*\d{4}[。.!！]?",
            r"[A-Za-z0-9][A-Za-z0-9_-]{5,63}[。.!！]?",
            r"\d{4}[。.!！]?",
        )
        return any(re.fullmatch(pattern, message.strip()) for pattern in patterns)

    def _llm_error_result(self, error_message: str) -> UnderstandingResult:
        """llm模式失败时返回未知意图，让策略层安全地向用户澄清。"""
        return UnderstandingResult(
            intent="unknown",
            confidence=0.0,
            needs_clarification=True,
            source="llm-error",
            error_message=error_message,
        )

    def _message_content_to_text(self, content: Any) -> str:
        """兼容LangChain返回字符串或多模态文本分块。"""
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, str):
                    parts.append(block)
                elif isinstance(block, dict) and isinstance(block.get("text"), str):
                    parts.append(block["text"])
            if parts:
                return "".join(parts)
        return str(content)
