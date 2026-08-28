from app.integrations.nacos import NacosClient


def test_extracts_nacos_323_backend_endpoint() -> None:
    """Nacos 3.2.3使用分离字段返回动态MCP实例，Python应组装成完整URL。"""
    payload = {
        "remoteServerConfig": {"exportPath": "/mcp"},
        "backendEndpoints": [
            {
                "protocol": None,
                "address": "127.0.0.1",
                "port": 8081,
                "path": "/mcp",
            }
        ],
    }

    assert NacosClient._extract_endpoint(payload) == "http://127.0.0.1:8081/mcp"


def test_extracts_ipv6_backend_endpoint() -> None:
    """IPv6地址需要方括号，否则生成的MCP URL无法被HTTP客户端解析。"""
    payload = {"address": "::1", "port": 8081, "path": "mcp"}

    assert NacosClient._extract_endpoint(payload) == "http://[::1]:8081/mcp"
