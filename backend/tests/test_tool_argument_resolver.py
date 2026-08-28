from app.tools.argument_resolver import ToolArgumentResolver
from app.tools.mcp_client import McpToolDefinition


def _definition(tool_name: str, field: str, description: str) -> McpToolDefinition:
    return McpToolDefinition(
        name=tool_name,
        description=f"测试工具 {tool_name}",
        input_schema={
            "type": "object",
            "properties": {
                "sessionId": {"type": "string"},
                field: {
                    "type": "string",
                    "minLength": 6,
                    "maxLength": 64,
                    "description": description,
                },
            },
            "required": ["sessionId", field],
        },
    )


def test_resolves_identifier_anywhere_in_parameter_only_message() -> None:
    resolver = ToolArgumentResolver()
    definition = _definition("order_query", "orderId", "用户需要查询的订单号")

    resolution = resolver.resolve_structured(
        "ORDER_20260809001 我的订单号",
        definition,
        {},
    )

    assert resolution.arguments == {"orderId": "ORDER_20260809001"}
    assert resolution.matched is True


def test_same_resolver_supports_other_tool_identifier_fields() -> None:
    resolver = ToolArgumentResolver()
    definition = _definition("reward_query", "rewardNo", "需要查询的奖励编号")

    resolution = resolver.resolve_structured(
        "奖励编号是 REWARD_20260809001",
        definition,
        {},
    )

    assert resolution.arguments == {"rewardNo": "REWARD_20260809001"}


def test_additional_business_request_does_not_take_fast_continuation() -> None:
    resolver = ToolArgumentResolver()
    definition = _definition("order_query", "orderId", "用户需要查询的订单号")

    resolution = resolver.resolve_structured(
        "ORDER_20260809001，我还要申请退款",
        definition,
        {},
    )

    assert resolution.matched is False
    assert resolution.arguments == {}


def test_multiple_identifiers_are_ambiguous() -> None:
    resolver = ToolArgumentResolver()
    definition = _definition("order_query", "orderId", "用户需要查询的订单号")

    resolution = resolver.resolve_structured(
        "查 ORDER_20260809001 还是 ORDER_20260809002",
        definition,
        {},
    )

    assert resolution.matched is False
    assert resolution.ambiguous_fields == ("orderId",)


def test_model_cannot_invent_identifier_not_present_in_user_message() -> None:
    resolver = ToolArgumentResolver()
    definition = _definition("order_query", "orderId", "用户需要查询的订单号")

    arguments = resolver.sanitize_model_arguments(
        "帮我查刚才那一单",
        definition,
        {"orderId": "ORDER_INVENTED_001"},
    )

    assert arguments == {}
