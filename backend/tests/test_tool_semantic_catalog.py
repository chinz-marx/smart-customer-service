import asyncio

from app.config import Settings
from app.tools.mcp_client import McpToolClient, McpToolDefinition
from app.tools.semantic_catalog import RedisToolSemanticCatalog


class FakeSemanticCatalog:
    """避免单元测试连接真实 Redis 和 Embedding 服务。"""

    def __init__(self, candidates: list[str] | None) -> None:
        self.candidates = candidates
        self.ready = True
        self.error = None

    async def candidate_names(self, message: str) -> list[str] | None:
        return self.candidates


def _definition(name: str) -> McpToolDefinition:
    """构造包含系统参数和用户参数的最小 Tool Schema。"""
    return McpToolDefinition(
        name=name,
        description=f"{name} 业务能力",
        input_schema={
            "type": "object",
            "properties": {
                "sessionId": {"type": "string", "description": "内部会话"},
                "requestId": {"type": "string", "description": "内部请求"},
                "orderId": {"type": "string", "description": "用户订单号"},
            },
            "required": ["sessionId", "requestId", "orderId"],
        },
    )


def _client(candidates: list[str] | None) -> McpToolClient:
    """创建不连接真实 MCP Server 的目录客户端。"""
    client = McpToolClient(Settings(tool_retrieval_enabled=False), None)
    client._tools = {
        name: _definition(name)
        for name in ("order_query", "refund_query", "points_query", "benefits_query")
    }
    client._semantic_catalog = FakeSemanticCatalog(candidates)
    return client


def test_candidate_catalog_keeps_vector_distance_order() -> None:
    """LLM 收到的 Tool 顺序应与 Redis Search 的距离排序一致。"""
    client = _client(["order_query", "refund_query", "points_query"])

    catalog = asyncio.run(client.candidate_catalog("帮我查订单"))

    assert [tool["name"] for tool in catalog] == [
        "order_query",
        "refund_query",
        "points_query",
    ]


def test_active_tool_is_forced_into_top_k_for_slot_followup() -> None:
    """用户只补充编号时没有业务语义，当前活动 Tool 仍必须排在候选首位。"""
    client = _client(["points_query", "benefits_query", "refund_query"])

    catalog = asyncio.run(
        client.candidate_catalog("ORDER_123456", active_tool="order_query")
    )

    assert [tool["name"] for tool in catalog] == [
        "order_query",
        "points_query",
        "benefits_query",
    ]


def test_retrieval_failure_falls_back_to_full_catalog() -> None:
    """召回超时、低相似度或 Redis 故障不能让任何业务 Tool 消失。"""
    client = _client(None)

    catalog = asyncio.run(client.candidate_catalog("我要办理业务"))

    assert [tool["name"] for tool in catalog] == [
        "order_query",
        "refund_query",
        "points_query",
        "benefits_query",
    ]


def test_retrieval_text_excludes_trusted_internal_arguments() -> None:
    """内部身份字段没有业务语义，不应占用向量文本和召回权重。"""
    text = RedisToolSemanticCatalog._build_retrieval_text(
        _definition("order_query").prompt_payload()
    )

    assert "order_query" in text
    assert "用户订单号" in text
    assert "sessionId" not in text
    assert "requestId" not in text


def test_search_response_is_decoded_to_candidate_rows() -> None:
    """兼容 redis-py 在 decode_responses=False 时返回的字节数组。"""
    rows = RedisToolSemanticCatalog._parse_search_rows(
        [
            2,
            b"cs:mcp:tool:order_query",
            [b"name", b"order_query", b"vector_distance", b"0.12"],
            b"cs:mcp:tool:refund_query",
            [b"name", b"refund_query", b"vector_distance", b"0.31"],
        ]
    )

    assert rows == [
        {"name": "order_query", "vector_distance": "0.12"},
        {"name": "refund_query", "vector_distance": "0.31"},
    ]
