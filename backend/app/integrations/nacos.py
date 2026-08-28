from __future__ import annotations

import logging
import json
import time
from typing import Any
from urllib.parse import urljoin, urlunsplit

import httpx

from app.config import Settings


logger = logging.getLogger("smart_customer_service.nacos")


class NacosClient:
    """访问 Nacos 3.x Prompt Registry 和 MCP Registry 的轻量异步客户端。

    Nacos只处于启动控制面：提示词和MCP地址会被上层缓存，聊天请求不会逐次访问Nacos。
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            base_url=settings.nacos_server_addr.rstrip("/"),
            timeout=settings.nacos_timeout_seconds,
        )
        self._access_token: str | None = None
        self._token_expires_at = 0.0

    async def close(self) -> None:
        """释放HTTP连接池。"""
        await self._client.aclose()

    async def get_prompt(self, prompt_key: str, label: str) -> str | None:
        """按标签读取已发布提示词，并兼容Nacos 3.2.3运行态缓存未刷新的情况。"""
        response = await self._request(
            "GET",
            "/nacos/v3/client/ai/prompt",
            params={
                "namespaceId": self.settings.nacos_namespace,
                "promptKey": prompt_key,
                "label": label,
            },
        )
        if response.status_code == 404:
            client_data: dict[str, Any] = {}
        else:
            response.raise_for_status()
            unwrapped = self._unwrap(response.json())
            client_data = unwrapped if isinstance(unwrapped, dict) else {}

        # 当前部署的Nacos 3.2.3可能出现Admin详情已切到新版本、Client API仍返回旧模板。
        # 这里只在配置了管理账号时做启动期校验；聊天请求不会逐次访问Nacos。
        admin_data: dict[str, Any] = {}
        if self.settings.nacos_username:
            try:
                governance_response = await self._request(
                    "GET",
                    "/nacos/v3/admin/ai/prompt/governance",
                    params={
                        "namespaceId": self.settings.nacos_namespace,
                        "promptKey": prompt_key,
                    },
                )
                governance = (
                    self._unwrap(governance_response.json())
                    if governance_response.is_success
                    else {}
                )
                labels = governance.get("labels", {}) if isinstance(governance, dict) else {}
                version = labels.get(label) if isinstance(labels, dict) else None
                if not version and isinstance(governance, dict):
                    version = governance.get("latestVersion")
                if version:
                    version_response = await self._request(
                        "GET",
                        "/nacos/v3/admin/ai/prompt/version",
                        params={
                            "namespaceId": self.settings.nacos_namespace,
                            "promptKey": prompt_key,
                            "version": version,
                        },
                    )
                    if version_response.is_success:
                        detail = self._unwrap(version_response.json())
                        admin_data = detail if isinstance(detail, dict) else {}
            except Exception as exc:
                logger.warning(
                    "Nacos提示词管理详情校验失败: key=%s, error=%s",
                    prompt_key,
                    type(exc).__name__,
                )

        data = admin_data or client_data
        if admin_data and client_data and admin_data.get("md5") != client_data.get("md5"):
            logger.warning(
                "Nacos Client提示词缓存与Admin版本不一致，采用Admin已发布版本: key=%s, version=%s",
                prompt_key,
                admin_data.get("version"),
            )
        for key in ("template", "promptTemplate", "content"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                return value
        return None

    async def discover_mcp_url(self, server_name: str) -> str | None:
        """从 Nacos AI Registry 查找指定 MCP Server 的 Streamable HTTP 地址。"""
        response = await self._request(
            "GET",
            "/nacos/v3/admin/ai/mcp/list",
            params={
                "namespaceId": self.settings.nacos_namespace,
                "mcpName": server_name,
                "pageNo": 1,
                "pageSize": 100,
            },
        )
        response.raise_for_status()
        payload = self._unwrap(response.json())
        records = self._find_records(payload)
        matched = next(
            (
                record
                for record in records
                if str(record.get("name") or record.get("mcpName") or "") == server_name
            ),
            None,
        )
        if not matched:
            return None

        server_id = matched.get("id") or matched.get("mcpId")
        if server_id:
            detail_response = await self._request(
                "GET",
                "/nacos/v3/admin/ai/mcp",
                params={
                    "namespaceId": self.settings.nacos_namespace,
                    "mcpId": server_id,
                },
            )
            if detail_response.is_success:
                matched = self._unwrap(detail_response.json()) or matched
        return self._extract_endpoint(matched)

    async def publish_prompt(
        self,
        *,
        prompt_key: str,
        version: str,
        template: str,
        description: str,
    ) -> None:
        """按Nacos 3.2.3生命周期创建一个待发布的Prompt草稿版本。"""
        response = await self._request(
            "POST",
            "/nacos/v3/admin/ai/prompt/draft",
            # targetVersion是新草稿的明确版本号，发布步骤随后只操作这个版本。
            data={
                "namespaceId": self.settings.nacos_namespace,
                "promptKey": prompt_key,
                "targetVersion": version,
                "template": template,
                "commitMsg": f"publish {version}",
                "description": description,
                "bizTags": "smart-customer-service",
                "variables": json.dumps([], ensure_ascii=False),
            },
        )
        self._require_api_success(response, f"创建提示词草稿{prompt_key}@{version}")

        # 3.2.3创建草稿时可能只采用版本元数据，显式更新一次确保模板进入草稿内容。
        update_response = await self._request(
            "PUT",
            "/nacos/v3/admin/ai/prompt/draft",
            data={
                "namespaceId": self.settings.nacos_namespace,
                "promptKey": prompt_key,
                "template": template,
                "variables": json.dumps([], ensure_ascii=False),
                "commitMsg": f"publish {version}",
            },
        )
        self._require_api_success(update_response, f"更新提示词草稿{prompt_key}@{version}")

    async def activate_prompt_version(self, *, prompt_key: str, version: str) -> None:
        """按Nacos 3.2.3资源生命周期发布并上线指定提示词版本。"""
        publish_response = await self._request(
            "POST",
            "/nacos/v3/admin/ai/prompt/force-publish",
            data={
                "namespaceId": self.settings.nacos_namespace,
                "promptKey": prompt_key,
                "version": version,
                "updateLatestLabel": "false",
            },
        )
        self._require_api_success(
            publish_response,
            f"发布提示词运行版本{prompt_key}@{version}",
        )

        online_response = await self._request(
            "POST",
            "/nacos/v3/admin/ai/prompt/online",
            data={
                "namespaceId": self.settings.nacos_namespace,
                "promptKey": prompt_key,
                "version": version,
            },
        )
        self._require_api_success(
            online_response,
            f"上线提示词{prompt_key}@{version}",
        )

    async def bind_prompt_label(
        self,
        *,
        prompt_key: str,
        version: str,
        label: str,
    ) -> None:
        """把stable等运行标签原子切换到指定提示词版本。"""
        response = await self._request(
            "PUT",
            "/nacos/v3/admin/ai/prompt/label",
            # 标签绑定接口同样使用表单参数，与Nacos官方curl示例保持一致。
            data={
                "namespaceId": self.settings.nacos_namespace,
                "promptKey": prompt_key,
                "version": version,
                "label": label,
            },
        )
        self._require_api_success(response, f"绑定提示词标签{prompt_key}:{label}")

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """携带Nacos访问令牌请求接口；401时刷新令牌后仅重试一次。"""
        token = await self._get_access_token()
        response = await self._send(method, path, token, **kwargs)
        if response.status_code in {401, 403}:
            self._access_token = None
            token = await self._get_access_token()
            response = await self._send(method, path, token, **kwargs)
        return response

    async def _send(
        self,
        method: str,
        path: str,
        token: str | None,
        **kwargs: Any,
    ) -> httpx.Response:
        params = dict(kwargs.pop("params", {}) or {})
        headers = dict(kwargs.pop("headers", {}) or {})
        if token:
            params["accessToken"] = token
            headers["Authorization"] = f"Bearer {token}"
        return await self._client.request(
            method,
            path,
            params=params,
            headers=headers,
            **kwargs,
        )

    async def _get_access_token(self) -> str | None:
        """登录Nacos并缓存令牌，避免每个启动步骤重复认证。"""
        if not self.settings.nacos_username:
            return None
        if self._access_token and time.monotonic() < self._token_expires_at:
            return self._access_token

        response = await self._client.post(
            "/nacos/v1/auth/login",
            data={
                "username": self.settings.nacos_username,
                "password": self.settings.nacos_password,
            },
        )
        response.raise_for_status()
        payload = response.json()
        token = payload.get("accessToken")
        if not isinstance(token, str) or not token:
            raise RuntimeError("Nacos登录响应中没有accessToken")
        ttl = int(payload.get("tokenTtl", 18000))
        self._access_token = token
        self._token_expires_at = time.monotonic() + max(60, ttl - 60)
        return token

    @staticmethod
    def _unwrap(payload: Any) -> Any:
        """兼容Nacos响应外层code/data包装。"""
        if isinstance(payload, dict) and "data" in payload:
            return payload["data"]
        return payload

    @staticmethod
    def _require_api_success(response: httpx.Response, operation: str) -> None:
        """同时检查HTTP状态和Nacos统一响应体，避免把业务失败当成成功。"""
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"{operation}失败：Nacos响应格式无效")
        code = payload.get("code")
        data = payload.get("data")
        if code not in {0, 200} or data is None or data is False:
            message = str(payload.get("message") or "unknown error")
            raise RuntimeError(f"{operation}失败：{message}")

    @staticmethod
    def _find_records(payload: Any) -> list[dict[str, Any]]:
        """从分页或直接数组响应中提取MCP记录。"""
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if isinstance(payload, dict):
            for key in ("pageItems", "list", "items", "records"):
                value = payload.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    @classmethod
    def _extract_endpoint(cls, payload: Any) -> str | None:
        """递归查找注册信息中的HTTP URL，并补齐标准/mcp路径。"""
        if isinstance(payload, str) and payload.startswith(("http://", "https://")):
            return payload if payload.rstrip("/").endswith("/mcp") else urljoin(payload.rstrip("/") + "/", "mcp")
        if isinstance(payload, dict):
            # Nacos 3.2.3的MCP详情把动态实例拆成address、port和path三个字段，
            # 不会直接返回完整URL。先按结构组装，随后再兼容旧版完整URL字段。
            address = payload.get("address")
            port = payload.get("port")
            if isinstance(address, str) and address.strip() and isinstance(port, int):
                if 1 <= port <= 65535:
                    host = address.strip()
                    # urlunsplit要求IPv6地址放在方括号内，IPv4和域名保持原样。
                    netloc = f"[{host}]:{port}" if ":" in host and not host.startswith("[") else f"{host}:{port}"
                    path = str(payload.get("path") or "/mcp").strip()
                    normalized_path = path if path.startswith("/") else f"/{path}"
                    return urlunsplit(("http", netloc, normalized_path, "", ""))
            for key in ("url", "endpoint", "address", "serverUrl"):
                endpoint = cls._extract_endpoint(payload.get(key))
                if endpoint:
                    return endpoint
            for value in payload.values():
                endpoint = cls._extract_endpoint(value)
                if endpoint:
                    return endpoint
        if isinstance(payload, list):
            for value in payload:
                endpoint = cls._extract_endpoint(value)
                if endpoint:
                    return endpoint
        return None
