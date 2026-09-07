import asyncio
import json

from app.config import Settings
from app.integrations.nacos import NacosConfigSnapshot
from app.rules.local_routing import (
    DEFAULT_LOCAL_ROUTING_CONFIG,
    LocalRoutingConfigRegistry,
)
from app.rules.quick_reply import QuickReplyMatcher


class FakeNacosConfigClient:
    def __init__(self, content: str, md5: str) -> None:
        self.content = content
        self.md5 = md5

    async def get_config(self, **kwargs) -> NacosConfigSnapshot:
        assert kwargs["data_id"] == "smart-customer-local-routing.json"
        assert kwargs["group_name"] == "SMART_CUSTOMER_SERVICE"
        return NacosConfigSnapshot(content=self.content, md5=self.md5)


def test_nacos_config_refresh_atomically_changes_local_rules() -> None:
    async def scenario() -> None:
        raw = json.loads(json.dumps(DEFAULT_LOCAL_ROUTING_CONFIG, ensure_ascii=False))
        raw["reply"] = "热更新回复"
        raw["routes"]["human_handoff"]["exact"].append("呼叫坐席")
        client = FakeNacosConfigClient(
            json.dumps(raw, ensure_ascii=False),
            "new-md5",
        )
        registry = LocalRoutingConfigRegistry(
            Settings(nacos_enabled=True),
            client,  # type: ignore[arg-type]
        )

        changed = await registry.refresh_once()
        reply = QuickReplyMatcher(registry).match("呼叫坐席")

        assert changed is True
        assert registry.source.startswith("nacos-config:")
        assert reply is not None
        assert reply.answer == "热更新回复"

    asyncio.run(scenario())
