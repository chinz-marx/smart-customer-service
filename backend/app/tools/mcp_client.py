from __future__ import annotations

import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import httpx
from jsonschema import ValidationError, validate
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings
from app.errors import safe_error_message
from app.integrations.nacos import NacosClient
from app.tools.semantic_catalog import RedisToolSemanticCatalog
from app.tools.schemas import ToolResult


logger = logging.getLogger("smart_customer_service.mcp")
_INTERNAL_ARGUMENTS = {"sessionId", "userId", "requestId"}


@dataclass(slots=True)
class McpToolDefinition:
    """Python编排层缓存的一份MCP Tool Schema。"""

    name: str
    description: str
    input_schema: dict[str, Any]

    @property
    def user_required_fields(self) -> list[str]:
        """只返回需要向用户收集的参数，排除由系统可信注入的上下文字段。"""
        required = self.input_schema.get("required", [])
        return [str(field) for field in required if str(field) not in _INTERNAL_ARGUMENTS]

    def prompt_payload(self) -> dict[str, Any]:
        """提供给语义理解模型的精简工具定义。"""
        properties = self.input_schema.get("properties", {})
        visible_properties = {
            key: value
            for key, value in properties.items()
            if key not in _INTERNAL_ARGUMENTS
        }
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": {
                "type": "object",
                "properties": visible_properties,
                "required": self.user_required_fields,
            },
        }


class McpToolClient:
    """通过官方MCP SDK调用Java业务工具。

    服务启动时建立一个Streamable HTTP会话并缓存Tool Schema；聊天主链路只执行
    tools/call，不再查询Nacos或重复获取工具列表。
    """

    def __init__(self, settings: Settings, nacos_client: NacosClient | None) -> None:
        self.settings = settings
        self.nacos_client = nacos_client
        self._stack = AsyncExitStack()
        self._session: ClientSession | None = None
        self._http_client: httpx.AsyncClient | None = None
        self._tools: dict[str, McpToolDefinition] = {}
        self._semantic_catalog = (
            RedisToolSemanticCatalog(settings)
            if settings.tool_retrieval_enabled
            else None
        )
        self.endpoint: str | None = None
        self.error: str | None = None

    async def initialize(self) -> None:
        """发现并连接Java MCP；失败时保留旧Tool作为降级，不阻止Python启动。"""
        if not self.settings.mcp_enabled:
            return
        try:
            endpoint = None
            if self.settings.nacos_enabled and self.nacos_client is not None:
                endpoint = await self.nacos_client.discover_mcp_url(
                    self.settings.mcp_server_name
                )
            self.endpoint = endpoint or self.settings.mcp_server_url
            self._http_client = await self._stack.enter_async_context(
                httpx.AsyncClient(
                    headers={
                        "X-Internal-Token": self.settings.business_tool_internal_token,
                    },
                    timeout=self.settings.business_tool_timeout_seconds,
                )
            )
            read_stream, write_stream, _ = await self._stack.enter_async_context(
                streamable_http_client(
                    self.endpoint,
                    http_client=self._http_client,
                )
            )
            self._session = await self._stack.enter_async_context(
                ClientSession(
                    read_stream,
                    write_stream,
                    read_timeout_seconds=timedelta(
                        seconds=self.settings.business_tool_timeout_seconds
                    ),
                )
            )
            await self._session.initialize()
            response = await self._session.list_tools()
            self._tools = {
                tool.name: McpToolDefinition(
                    name=tool.name,
                    description=tool.description or "",
                    input_schema=tool.inputSchema,
                )
                for tool in response.tools
            }
            if self._semantic_catalog is not None:
                try:
                    # Tool Schema 以 Java MCP 当前实际暴露的目录为准，内容未变化时不会重复生成向量。
                    await self._semantic_catalog.initialize(self.catalog())
                except Exception as exc:
                    # 召回只是 Prompt 加速层，初始化失败不能让真实业务 Tool 整体离线。
                    self._semantic_catalog.error = exc.__class__.__name__
                    logger.warning(
                        "Tool 向量目录初始化失败，保留完整 MCP 目录: error=%s",
                        self._semantic_catalog.error,
                    )
            self.error = None
            logger.info("MCP连接完成: endpoint=%s, tools=%s", self.endpoint, list(self._tools))
        except Exception as exc:
            self.error = safe_error_message(exc)
            logger.warning("MCP连接失败，保留旧Tool降级: error=%s", type(exc).__name__)
            await self.close()

    async def close(self) -> None:
        """关闭MCP会话以及其HTTP连接池。"""
        if self._semantic_catalog is not None:
            await self._semantic_catalog.close()
        await self._stack.aclose()
        self._stack = AsyncExitStack()
        self._session = None
        self._http_client = None

    def catalog(self, tool_names: list[str] | None = None) -> list[dict[str, Any]]:
        """返回适合放入语义理解提示词的MCP工具目录。"""
        if tool_names is None:
            definitions = list(self._tools.values())
        else:
            # 按向量距离保留候选顺序，同时忽略已经从动态 MCP 目录删除的旧名称。
            definitions = [
                self._tools[name]
                for name in tool_names
                if name in self._tools
            ]
        return [tool.prompt_payload() for tool in definitions]

    async def candidate_catalog(
        self,
        message: str,
        active_tool: str | None = None,
    ) -> list[dict[str, Any]]:
        """先召回 Top K 工具；不可用时返回完整目录保证业务召回率。"""
        full_catalog = self.catalog()
        if self._semantic_catalog is None:
            return full_catalog

        candidate_names = await self._semantic_catalog.candidate_names(message)
        if candidate_names is None:
            return full_catalog

        # 用户在多轮中可能只补充订单号，文本本身不再包含 Tool 业务语义，必须保留活动工具。
        ordered_names: list[str] = []
        if active_tool and active_tool in self._tools:
            ordered_names.append(active_tool)
        ordered_names.extend(
            name for name in candidate_names if name not in ordered_names
        )
        selected = self.catalog(ordered_names[: self.settings.tool_retrieval_top_k])
        return selected or full_catalog

    @property
    def tool_retrieval_status(self) -> str:
        """提供给健康检查使用，不暴露 Redis 或模型异常的敏感细节。"""
        if self._semantic_catalog is None:
            return "disabled"
        return "ready" if self._semantic_catalog.ready else "degraded"

    def get_tool(self, tool_name: str | None) -> McpToolDefinition | None:
        """按名称读取缓存Schema。"""
        return self._tools.get(tool_name or "")

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        session_id: str,
        user_id: str,
        request_id: str,
    ) -> ToolResult:
        """校验参数、注入可信上下文并执行MCP tools/call。"""
        definition = self.get_tool(tool_name)
        if definition is None or self._session is None:
            return ToolResult.skipped(tool_name, "MCP业务工具暂时不可用。")

        trusted_arguments = dict(arguments)
        trusted_arguments.update(
            {
                "sessionId": session_id,
                "userId": user_id,
                "requestId": request_id,
            }
        )
        try:
            validate(instance=trusted_arguments, schema=definition.input_schema)
        except ValidationError as exc:
            return ToolResult.failed(
                tool_name,
                f"业务参数校验失败：{exc.message}",
                "ToolArgumentValidationError",
            )

        try:
            response = await self._session.call_tool(tool_name, trusted_arguments)
            payload = self._result_payload(response)
            message = str(payload.get("answer") or payload.get("message") or "").strip()
            if response.isError:
                return ToolResult.failed(
                    tool_name,
                    message or "业务工具执行失败。",
                    "McpToolError",
                )
            return ToolResult(
                tool_name=tool_name,
                success=True,
                data=payload,
                message=message,
                direct_answer=bool(message),
            )
        except Exception as exc:
            return ToolResult.failed(
                tool_name,
                safe_error_message(exc),
                exc.__class__.__name__,
            )

    @staticmethod
    def _result_payload(response: Any) -> dict[str, Any]:
        """优先读取结构化结果；兼容只返回JSON文本的MCP Server。"""
        if isinstance(response.structuredContent, dict):
            # Spring AI可能把真实结果包装在result或content字段中。
            structured = response.structuredContent
            for key in ("result", "content"):
                if isinstance(structured.get(key), dict):
                    return structured[key]
            return structured

        texts = [
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text" and getattr(block, "text", None)
        ]
        text = "".join(texts).strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
            return parsed if isinstance(parsed, dict) else {"result": parsed}
        except json.JSONDecodeError:
            return {"answer": text}
