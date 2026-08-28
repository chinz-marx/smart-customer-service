from __future__ import annotations

import logging

from app.config import Settings
from app.integrations.nacos import NacosClient
from app.prompts.defaults import DEFAULT_PROMPTS


logger = logging.getLogger("smart_customer_service.prompts")


class PromptRegistry:
    """启动时加载并在内存中保存当前生效的全部提示词。"""

    def __init__(self, settings: Settings, nacos_client: NacosClient | None) -> None:
        self.settings = settings
        self.nacos_client = nacos_client
        self._prompts = dict(DEFAULT_PROMPTS)
        self.source = "local-default"

    async def initialize(self) -> None:
        """从Nacos读取stable版本；单条失败时保留该条本地模板。"""
        if not self.settings.nacos_enabled or self.nacos_client is None:
            return
        loaded = 0
        for key in DEFAULT_PROMPTS:
            try:
                value = await self.nacos_client.get_prompt(
                    key,
                    self.settings.nacos_prompt_label,
                )
            except Exception as exc:
                logger.warning("Nacos提示词读取失败: key=%s, error=%s", key, type(exc).__name__)
                continue
            if value:
                self._prompts[key] = value
                loaded += 1
        if loaded:
            self.source = f"nacos:{self.settings.nacos_prompt_label}"
        logger.info("提示词加载完成: nacos=%s, fallback=%s", loaded, len(DEFAULT_PROMPTS) - loaded)

    def get(self, key: str) -> str:
        """读取提示词；未知Key属于程序错误，直接抛出便于尽早发现。"""
        return self._prompts[key]
