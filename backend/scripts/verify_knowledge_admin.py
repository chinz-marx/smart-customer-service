from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import asyncpg
import httpx


# 直接运行脚本时把backend根目录加入模块路径，兼容Windows和Linux。
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.config import get_settings


JAVA_URL = "http://127.0.0.1:8081/api/admin/knowledge"
PYTHON_URL = "http://127.0.0.1:8000/api/internal/knowledge"
AUTHOR = "integration-author"
REVIEWER = "integration-reviewer"


async def main() -> int:
    """验证新增、审批发布、停用审批和索引删除，并清理测试数据。"""
    settings = get_settings()
    knowledge_id: int | None = None
    knowledge_code: str | None = None
    async with httpx.AsyncClient(timeout=60) as client:
        try:
            categories = await api_get(client, f"{JAVA_URL}/categories")
            faq = next(item for item in categories if item["categoryName"] == "FAQ")
            now = datetime.now(timezone.utc).isoformat()
            created = await api_request(
                client,
                "POST",
                JAVA_URL,
                AUTHOR,
                {
                    "title": "集成测试知识",
                    "categoryId": faq["id"],
                    "content": "这条知识仅用于验证审批与Redis发布闭环。",
                    "tags": ["integration-test"],
                    "intentCode": "activity_rules",
                    "effectiveAt": now,
                    "applicationReason": "自动化闭环验证",
                },
            )
            knowledge_id = int(created["knowledge"]["id"])
            knowledge_code = str(created["knowledge"]["knowledgeCode"])
            assert created["pendingVersion"] is not None

            approval = await find_pending_approval(client, knowledge_id)
            await api_request(
                client,
                "POST",
                f"{JAVA_URL}/approvals/{approval['approvalId']}/approve",
                REVIEWER,
                {"comment": "自动化审批通过"},
            )
            await wait_for_outbox(settings.database_url, knowledge_id, expected_chunks=1)

            published = await api_get(client, f"{JAVA_URL}/{knowledge_id}")
            assert published["knowledge"]["status"] == 1
            assert published["currentVersion"]["versionStatus"] == 2

            await api_request(
                client,
                "DELETE",
                f"{JAVA_URL}/{knowledge_id}",
                AUTHOR,
            )
            disable_approval = await find_pending_approval(client, knowledge_id)
            await api_request(
                client,
                "POST",
                f"{JAVA_URL}/approvals/{disable_approval['approvalId']}/approve",
                REVIEWER,
                {"comment": "自动化停用审批通过"},
            )
            await wait_for_outbox(settings.database_url, knowledge_id, expected_chunks=0)

            disabled = await api_get(client, f"{JAVA_URL}/{knowledge_id}")
            assert disabled["knowledge"]["status"] == 0
            print("知识管理闭环通过: create -> approve -> Redis -> disable -> Redis delete")
            return 0
        finally:
            if knowledge_id is not None:
                # 即使中途断言失败，也只删除本脚本创建的稳定ID，不影响业务知识。
                if knowledge_code:
                    await client.post(
                        f"{PYTHON_URL}/delete",
                        headers={"X-Internal-Token": settings.business_tool_internal_token},
                        json={"knowledge_id": knowledge_id, "knowledge_code": knowledge_code},
                    )
                await cleanup_database(settings.database_url, knowledge_id)


async def api_get(client: httpx.AsyncClient, url: str) -> Any:
    response = await client.get(url)
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(payload)
    return payload["data"]


async def api_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    operator_id: str,
    body: dict[str, Any] | None = None,
) -> Any:
    response = await client.request(
        method,
        url,
        headers={"X-Operator-Id": operator_id},
        json=body,
    )
    response.raise_for_status()
    payload = response.json()
    if not payload.get("success"):
        raise AssertionError(payload)
    return payload["data"]


async def find_pending_approval(
    client: httpx.AsyncClient, knowledge_id: int
) -> dict[str, Any]:
    page = await api_get(client, f"{JAVA_URL}/approvals?page=1&size=100")
    return next(
        item for item in page["records"] if int(item["knowledgeId"]) == knowledge_id
    )


async def wait_for_outbox(
    sqlalchemy_url: str, knowledge_id: int, expected_chunks: int
) -> None:
    connection = await asyncpg.connect(
        sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        for _ in range(40):
            event = await connection.fetchrow(
                "SELECT status, last_error FROM business.kb_outbox_event "
                "WHERE knowledge_id=$1 ORDER BY id DESC LIMIT 1",
                knowledge_id,
            )
            chunk_count = await connection.fetchval(
                "SELECT COUNT(*) FROM business.kb_knowledge_chunk WHERE knowledge_id=$1",
                knowledge_id,
            )
            if event and event["status"] == 2 and chunk_count == expected_chunks:
                return
            if event and event["status"] == 3:
                raise AssertionError(f"Outbox同步失败: {event['last_error']}")
            await asyncio.sleep(1)
        raise TimeoutError("等待知识Outbox同步超时")
    finally:
        await connection.close()


async def cleanup_database(sqlalchemy_url: str, knowledge_id: int) -> None:
    connection = await asyncpg.connect(
        sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://")
    )
    try:
        async with connection.transaction():
            await connection.execute(
                "DELETE FROM business.kb_operation_log WHERE knowledge_id=$1", knowledge_id
            )
            await connection.execute(
                "DELETE FROM business.kb_knowledge_chunk WHERE knowledge_id=$1", knowledge_id
            )
            await connection.execute(
                "DELETE FROM business.kb_outbox_event WHERE knowledge_id=$1", knowledge_id
            )
            await connection.execute(
                "DELETE FROM business.kb_approval WHERE knowledge_id=$1", knowledge_id
            )
            await connection.execute(
                "UPDATE business.kb_knowledge SET current_version_id=NULL, "
                "pending_version_id=NULL WHERE id=$1",
                knowledge_id,
            )
            await connection.execute(
                "DELETE FROM business.kb_knowledge_version WHERE knowledge_id=$1", knowledge_id
            )
            await connection.execute(
                "DELETE FROM business.kb_knowledge WHERE id=$1", knowledge_id
            )
    finally:
        await connection.close()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
