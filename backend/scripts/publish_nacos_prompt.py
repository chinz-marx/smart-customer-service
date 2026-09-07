from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.integrations.nacos import NacosClient
from app.prompts.defaults import DEFAULT_PROMPTS


async def publish(prompt_key: str, version: str, label: str) -> None:
    settings = get_settings()
    if not settings.nacos_enabled:
        raise RuntimeError("请先在backend/.env中设置NACOS_ENABLED=true")
    if prompt_key not in DEFAULT_PROMPTS:
        raise ValueError(f"未知提示词：{prompt_key}")

    client = NacosClient(settings)
    try:
        await client.publish_prompt(
            prompt_key=prompt_key,
            version=version,
            template=DEFAULT_PROMPTS[prompt_key],
            description="智能客服Python运行提示词",
        )
        await client.activate_prompt_version(prompt_key=prompt_key, version=version)
        await client.bind_prompt_label(prompt_key=prompt_key, version=version, label=label)
        loaded = await client.get_prompt(prompt_key, label)
        if loaded != DEFAULT_PROMPTS[prompt_key]:
            raise RuntimeError("Nacos发布后读取内容不一致")
        print(f"published: {prompt_key}@{version} -> {label}")
    finally:
        await client.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="仅发布一个智能客服提示词到Nacos")
    parser.add_argument("--key", required=True, choices=sorted(DEFAULT_PROMPTS))
    parser.add_argument("--version", required=True)
    parser.add_argument("--label", default="stable")
    args = parser.parse_args()
    asyncio.run(publish(args.key, args.version, args.label))


if __name__ == "__main__":
    main()
