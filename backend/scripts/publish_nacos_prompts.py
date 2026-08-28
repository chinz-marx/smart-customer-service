from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


# 直接执行scripts下文件时，Python默认只把scripts目录加入模块搜索路径。
# 显式加入backend目录后，Windows和Linux都能用同一条命令导入app包。
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings
from app.integrations.nacos import NacosClient
from app.prompts.defaults import DEFAULT_PROMPTS


async def publish(version: str, label: str) -> None:
    """创建、发布并上线全部提示词后，再逐条绑定运行标签。"""
    settings = get_settings()
    if not settings.nacos_enabled:
        raise RuntimeError("请先在backend/.env中设置NACOS_ENABLED=true")

    client = NacosClient(settings)
    try:
        for key, template in DEFAULT_PROMPTS.items():
            await client.publish_prompt(
                prompt_key=key,
                version=version,
                template=template,
                description="智能客服Python运行提示词",
            )
            # Nacos 3.2.3把版本创建、发布和上线分开管理，运行标签只能指向已上线版本。
            await client.activate_prompt_version(
                prompt_key=key,
                version=version,
            )
            await client.bind_prompt_label(
                prompt_key=key,
                version=version,
                label=label,
            )
            print(f"published: {key}@{version} -> {label}")
    finally:
        await client.close()


def main() -> None:
    """解析命令行参数；脚本在Windows PowerShell和Linux shell下用法一致。"""
    parser = argparse.ArgumentParser(description="发布智能客服提示词到Nacos")
    parser.add_argument("--version", default="1.0.0")
    parser.add_argument("--label", default="stable")
    args = parser.parse_args()
    asyncio.run(publish(args.version, args.label))


if __name__ == "__main__":
    main()
