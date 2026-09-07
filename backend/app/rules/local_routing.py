from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any

from app.config import Settings
from app.integrations.nacos import NacosClient


logger = logging.getLogger("smart_customer_service.rules.local_routing")

DEFAULT_UNAVAILABLE_REPLY = "当前人工坐席繁忙，已记录您的问题，请稍后再试"

DEFAULT_LOCAL_ROUTING_CONFIG: dict[str, Any] = {
    "version": 1,
    "enabled": True,
    "reply": DEFAULT_UNAVAILABLE_REPLY,
    "routes": {
        "human_handoff": {
            "enabled": True,
            "exact": [
                "人工",
                "人工客服",
                "真人客服",
                "转人工",
                "找真人",
                "联系人工客服",
                "转接人工客服",
            ],
            "contains": [
                "我要转人工",
                "我想转人工",
                "帮我转人工",
                "给我转人工",
                "转接人工客服",
                "联系人工客服",
                "我要找真人",
                "帮我找真人",
                "找人工客服",
                "我要人工客服",
            ],
        },
        "complaint": {
            "enabled": True,
            "exact": [
                "投诉",
                "我要投诉",
                "投诉客服",
                "我要投诉客服",
                "客服态度很差",
                "服务态度很差",
            ],
            "contains": [
                "我要投诉",
                "投诉你们",
                "客服态度很差",
                "客服态度太差",
                "客服服务很差",
                "客服服务太差",
                "服务态度很差",
                "服务态度太差",
                "对客服不满",
                "客服太垃圾",
            ],
        },
    },
}


@dataclass(frozen=True, slots=True)
class PhraseRule:
    enabled: bool
    exact: frozenset[str]
    contains: tuple[str, ...]

    def matches(self, text: str) -> bool:
        if not self.enabled:
            return False
        return text in self.exact or any(phrase in text for phrase in self.contains)


@dataclass(frozen=True, slots=True)
class LocalRoutingConfig:
    enabled: bool
    reply: str
    human_handoff: PhraseRule
    complaint: PhraseRule

    def match(self, text: str) -> str | None:
        if not self.enabled:
            return None
        # 投诉优先，确保“我要投诉并转人工”进入高优先级投诉问题学习信号。
        if self.complaint.matches(text):
            return "complaint"
        if self.human_handoff.matches(text):
            return "human_handoff"
        return None


class LocalRoutingConfigRegistry:
    """Nacos配置中心驱动的本地确定性路由，聊天线程只读取内存快照。"""

    def __init__(self, settings: Settings, nacos_client: NacosClient | None) -> None:
        self.settings = settings
        self.nacos_client = nacos_client
        self._config = self._parse(DEFAULT_LOCAL_ROUTING_CONFIG)
        self._md5 = self._content_md5(self.default_content())
        self.source = "local-default"
        self._stopped = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def config(self) -> LocalRoutingConfig:
        return self._config

    @classmethod
    def local_default(cls) -> LocalRoutingConfig:
        """返回不依赖环境变量和网络的内置兜底规则。"""
        return cls._parse(DEFAULT_LOCAL_ROUTING_CONFIG)

    async def initialize(self) -> None:
        """启动时读取一次配置，并在Nacos启用时开始MD5轮询热更新。"""
        if not self.settings.nacos_enabled or self.nacos_client is None:
            return
        await self.refresh_once()
        self._task = asyncio.create_task(
            self._run_forever(), name="nacos-local-routing-refresh"
        )

    async def close(self) -> None:
        self._stopped.set()
        if self._task is not None:
            self._task.cancel()
            with suppress(asyncio.CancelledError):
                await self._task

    async def refresh_once(self) -> bool:
        """读取并校验一份配置；内容无变化或读取失败时保留当前有效快照。"""
        if self.nacos_client is None:
            return False
        try:
            snapshot = await self.nacos_client.get_config(
                data_id=self.settings.nacos_local_rule_data_id,
                group_name=self.settings.nacos_local_rule_group,
            )
            if snapshot is None:
                logger.warning(
                    "Nacos本地路由配置不存在，继续使用当前配置: group=%s, data_id=%s",
                    self.settings.nacos_local_rule_group,
                    self.settings.nacos_local_rule_data_id,
                )
                return False
            effective_md5 = snapshot.md5 or self._content_md5(snapshot.content)
            if effective_md5 == self._md5 and self.source != "local-default":
                return False
            raw = json.loads(snapshot.content)
            config = self._parse(raw)
        except Exception as exc:
            logger.warning(
                "Nacos本地路由配置刷新失败，保留当前版本: error_type=%s",
                type(exc).__name__,
            )
            return False

        # asyncio事件循环内的对象引用替换是原子的，正在处理的请求继续使用旧快照。
        self._config = config
        self._md5 = effective_md5
        self.source = (
            f"nacos-config:{self.settings.nacos_local_rule_group}/"
            f"{self.settings.nacos_local_rule_data_id}"
        )
        logger.info("Nacos本地路由配置已热更新: md5=%s", effective_md5)
        return True

    async def _run_forever(self) -> None:
        interval = max(1.0, self.settings.nacos_local_rule_refresh_seconds)
        while not self._stopped.is_set():
            try:
                await asyncio.wait_for(self._stopped.wait(), timeout=interval)
                break
            except TimeoutError:
                await self.refresh_once()

    @classmethod
    def default_content(cls) -> str:
        return json.dumps(DEFAULT_LOCAL_ROUTING_CONFIG, ensure_ascii=False, indent=2)

    @classmethod
    def _parse(cls, raw: Any) -> LocalRoutingConfig:
        if not isinstance(raw, dict):
            raise ValueError("本地路由配置必须是JSON对象")
        reply = str(raw.get("reply") or "").strip()
        if not reply or len(reply) > 200:
            raise ValueError("本地路由回复不能为空且不能超过200字符")
        routes = raw.get("routes")
        if not isinstance(routes, dict):
            raise ValueError("本地路由配置缺少routes")
        return LocalRoutingConfig(
            enabled=bool(raw.get("enabled", True)),
            reply=reply,
            human_handoff=cls._parse_rule(routes.get("human_handoff")),
            complaint=cls._parse_rule(routes.get("complaint")),
        )

    @staticmethod
    def _parse_rule(raw: Any) -> PhraseRule:
        if not isinstance(raw, dict):
            raise ValueError("路由规则必须是JSON对象")

        def values(name: str) -> tuple[str, ...]:
            source = raw.get(name, [])
            if not isinstance(source, list) or len(source) > 100:
                raise ValueError(f"{name}必须是最多100项的数组")
            result: list[str] = []
            for item in source:
                value = str(item).strip().lower()
                if not value or len(value) > 80:
                    raise ValueError(f"{name}包含无效短语")
                if value not in result:
                    result.append(value)
            return tuple(result)

        exact = values("exact")
        contains = values("contains")
        if not exact and not contains:
            raise ValueError("每条路由至少需要一个匹配短语")
        return PhraseRule(
            enabled=bool(raw.get("enabled", True)),
            exact=frozenset(exact),
            contains=contains,
        )

    @staticmethod
    def _content_md5(content: str) -> str:
        return hashlib.md5(content.encode("utf-8"), usedforsecurity=False).hexdigest()
