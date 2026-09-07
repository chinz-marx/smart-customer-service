from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.integrations.nacos import NacosClient
from app.rules.local_routing import LocalRoutingConfigRegistry


async def publish() -> None:
    """把内置兜底规则发布到Nacos配置中心，后续可直接在控制台热更新。"""
    settings = get_settings()
    if not settings.nacos_enabled:
        raise RuntimeError("请先在backend/.env中设置NACOS_ENABLED=true")

    client = NacosClient(settings)
    try:
        content = LocalRoutingConfigRegistry.default_content()
        await client.publish_config(
            data_id=settings.nacos_local_rule_data_id,
            group_name=settings.nacos_local_rule_group,
            content=content,
            description="智能客服明确人工诉求与投诉的本地确定性路由",
        )
        snapshot = await client.get_config(
            data_id=settings.nacos_local_rule_data_id,
            group_name=settings.nacos_local_rule_group,
        )
        if snapshot is None or json.loads(snapshot.content) != json.loads(content):
            raise RuntimeError("Nacos配置发布后读取校验失败")
        print(
            "published: "
            f"{settings.nacos_local_rule_group}/{settings.nacos_local_rule_data_id} "
            f"md5={snapshot.md5}"
        )
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(publish())
