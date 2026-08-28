from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.tools.mcp_client import McpToolDefinition


_INTERNAL_ARGUMENTS = {"sessionId", "userId", "requestId"}
_IDENTIFIER_HINTS = ("编号", "单号", "号码", "尾号", "代码", "令牌", "标识")
_SAFE_FILLER_PATTERN = re.compile(
    r"(?:我(?:的)?|这个|就是|是|为|请|帮我|麻烦|查一下|查询|看一下|"
    r"订单号|单号|编号|号码|尾号|代码|令牌|标识|参数|值|ID|id)",
)
_IDENTIFIER_LABEL_PATTERN = re.compile(
    r"[\u4e00-\u9fff]{0,8}(?:订单号|单号|编号|号码|尾号|代码|令牌|标识)"
)
_IDENTIFIER_PATTERN = re.compile(r"(?<![A-Za-z0-9_-])([A-Za-z0-9][A-Za-z0-9_-]{5,63})(?![A-Za-z0-9_-])")
_NUMBER_PATTERN = re.compile(r"(?<![A-Za-z0-9.])-?\d+(?:\.\d+)?(?![A-Za-z0-9.])")


@dataclass(slots=True)
class ToolArgumentResolution:
    """当前 Tool 一轮结构化参数续填的结果。"""

    arguments: dict[str, str] = field(default_factory=dict)
    ambiguous_fields: tuple[str, ...] = ()

    @property
    def matched(self) -> bool:
        return bool(self.arguments) and not self.ambiguous_fields


class ToolArgumentResolver:
    """根据 MCP Schema 解析所有 Tool 的待补参数。

    这里只处理能从原文确定性还原的结构化值。自然语言、多个候选或包含额外诉求的
    输入交给当前 Tool 的轻量理解模型，避免规则层猜测用户意图或生成业务参数。
    """

    def missing_fields(
        self,
        definition: McpToolDefinition,
        existing_arguments: dict[str, str],
    ) -> list[str]:
        return [
            field
            for field in definition.user_required_fields
            if not str(existing_arguments.get(field, "")).strip()
        ]

    def resolve_structured(
        self,
        message: str,
        definition: McpToolDefinition,
        existing_arguments: dict[str, str],
    ) -> ToolArgumentResolution:
        """唯一命中且整句只是在补参数时返回参数，否则保守地交给模型。"""
        missing = self.missing_fields(definition, existing_arguments)
        if not missing:
            return ToolArgumentResolution()

        properties = definition.input_schema.get("properties", {})
        resolved: dict[str, str] = {}
        ambiguous: list[str] = []
        for field in missing:
            raw_schema = properties.get(field, {})
            schema = raw_schema if isinstance(raw_schema, dict) else {}
            candidates = self._candidate_values(message, field, schema)
            if len(candidates) > 1:
                ambiguous.append(field)
            elif len(candidates) == 1:
                resolved[field] = candidates[0]

        if ambiguous:
            return ToolArgumentResolution(ambiguous_fields=tuple(ambiguous))
        if not resolved or not self._is_parameter_only_message(message, resolved.values()):
            return ToolArgumentResolution()
        return ToolArgumentResolution(arguments=resolved)

    def sanitize_model_arguments(
        self,
        message: str,
        definition: McpToolDefinition,
        arguments: dict[str, str],
    ) -> dict[str, str]:
        """过滤模型参数；标识符必须来自用户原文，不能接受模型猜测的编号。"""
        properties = definition.input_schema.get("properties", {})
        sanitized: dict[str, str] = {}
        for field, raw_value in arguments.items():
            if field in _INTERNAL_ARGUMENTS or field not in properties:
                continue
            value = str(raw_value).strip()
            if not value:
                continue
            raw_schema = properties.get(field, {})
            schema = raw_schema if isinstance(raw_schema, dict) else {}
            if not self._matches_schema(value, schema):
                continue
            if self._is_identifier_field(field, schema) and value.casefold() not in message.casefold():
                continue
            sanitized[field] = value
        return sanitized

    def _candidate_values(
        self,
        message: str,
        field: str,
        schema: dict[str, Any],
    ) -> list[str]:
        enum_values = schema.get("enum")
        if isinstance(enum_values, list) and enum_values:
            return self._unique(
                str(value)
                for value in enum_values
                if str(value).casefold() in message.casefold()
                and self._matches_schema(str(value), schema)
            )

        field_type = schema.get("type", "string")
        if field_type in {"integer", "number"}:
            return self._unique(
                match.group(0)
                for match in _NUMBER_PATTERN.finditer(message)
                if self._matches_schema(match.group(0), schema)
            )
        if field_type == "string" and self._is_identifier_field(field, schema):
            return self._unique(
                match.group(1)
                for match in _IDENTIFIER_PATTERN.finditer(message)
                if self._matches_schema(match.group(1), schema)
            )
        return []

    @staticmethod
    def _unique(values: Any) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.casefold()
            if normalized not in seen:
                seen.add(normalized)
                result.append(value)
        return result

    @staticmethod
    def _is_identifier_field(field: str, schema: dict[str, Any]) -> bool:
        normalized = field.casefold().replace("_", "")
        if normalized.endswith(("id", "no", "number", "code", "token")):
            return True
        description = str(schema.get("description") or "")
        return any(hint in description for hint in _IDENTIFIER_HINTS)

    @staticmethod
    def _matches_schema(value: str, schema: dict[str, Any]) -> bool:
        min_length = schema.get("minLength")
        max_length = schema.get("maxLength")
        if isinstance(min_length, int) and len(value) < min_length:
            return False
        if isinstance(max_length, int) and len(value) > max_length:
            return False
        pattern = schema.get("pattern")
        if isinstance(pattern, str):
            try:
                if re.fullmatch(pattern, value) is None:
                    return False
            except re.error:
                return False
        return True

    @staticmethod
    def _is_parameter_only_message(message: str, values: Any) -> bool:
        remainder = message
        for value in values:
            remainder = re.sub(re.escape(str(value)), " ", remainder, count=1, flags=re.IGNORECASE)
        remainder = re.sub(r"[\s，,。；;：:!?！？、()（）\[\]【】'\"]+", "", remainder)
        # “奖励编号”“退款单号”等标签来自各 Tool 的业务字段，统一按结构后缀清理，
        # 不在解析器里枚举具体 Tool 名称。
        remainder = _IDENTIFIER_LABEL_PATTERN.sub("", remainder)
        previous = None
        while remainder and previous != remainder:
            previous = remainder
            remainder = _SAFE_FILLER_PATTERN.sub("", remainder)
        return not remainder
