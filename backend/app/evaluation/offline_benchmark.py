from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import uuid
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field


BenchmarkType = Literal["retrieval", "intent"]
BenchmarkStatus = Literal[
    "queued", "running", "completed", "passed", "failed", "system_failed"
]
CommandRunner = Callable[[list[str], Path], Awaitable[tuple[int, str, str]]]

_TYPE_LABELS: dict[str, str] = {"retrieval": "知识召回", "intent": "意图识别"}
_STATUS_LABELS: dict[str, str] = {
    "queued": "等待执行",
    "running": "执行中",
    "completed": "已完成",
    "passed": "已通过",
    "failed": "未通过",
    "system_failed": "系统失败",
}


class BenchmarkDataset(BaseModel):
    id: str
    name: str
    description: str
    evaluation_type: BenchmarkType
    case_count: int
    has_acceptance_thresholds: bool


class BenchmarkRun(BaseModel):
    run_id: str
    dataset_id: str
    dataset_name: str
    evaluation_type: BenchmarkType
    status: BenchmarkStatus
    case_count: int
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    metrics: dict[str, Any] = Field(default_factory=dict)
    acceptance: dict[str, Any] | None = None
    error_message: str | None = None
    stdout_summary: str | None = None
    json_report_name: str | None = None
    markdown_report_name: str | None = None


def report_download_name(run: BenchmarkRun, report_format: str) -> str:
    """使用业务信息生成可读且兼容 Windows 的报告下载文件名。"""
    completed_at = run.finished_at or run.started_at or run.created_at
    completed_text = completed_at.astimezone().strftime("%Y%m%d-%H%M%S")
    raw_name = "_".join((
        run.dataset_name,
        _TYPE_LABELS.get(run.evaluation_type, run.evaluation_type),
        f"{run.case_count}条",
        _STATUS_LABELS.get(run.status, run.status),
        completed_text,
    ))
    safe_name = re.sub(r'[\\/:*?"<>|\s]+', "_", raw_name).strip("._")
    extension = "json" if report_format == "json" else "md"
    return f"{safe_name}.{extension}"


class StartBenchmarkRequest(BaseModel):
    dataset_id: str = Field(min_length=1, max_length=128)


class _DatasetDefinition(BaseModel):
    id: str
    name: str
    evaluation_type: BenchmarkType
    dataset_path: Path
    script_path: Path
    extra_args: tuple[str, ...] = ()


class OfflineBenchmarkManager:
    """用固定白名单启动离线评测脚本，并持久化任务摘要和报告。"""

    def __init__(
        self,
        backend_dir: Path | None = None,
        report_root: Path | None = None,
        command_runner: CommandRunner | None = None,
    ) -> None:
        self.backend_dir = (backend_dir or Path(__file__).resolve().parents[2]).resolve()
        self.report_root = (
            report_root
            or self.backend_dir / "evaluation" / "reports" / "offline-runs"
        ).resolve()
        self.report_root.mkdir(parents=True, exist_ok=True)
        self._command_runner = command_runner or self._run_command
        self._definitions = self._build_definitions()
        self._runs = self._load_runs()
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._lock = asyncio.Lock()

    def list_datasets(self) -> list[BenchmarkDataset]:
        return [self._read_dataset(item) for item in self._definitions.values()]

    def list_runs(self, limit: int = 20) -> list[BenchmarkRun]:
        return sorted(
            self._runs.values(), key=lambda item: item.created_at, reverse=True
        )[: max(1, min(limit, 100))]

    def get_run(self, run_id: str) -> BenchmarkRun:
        run = self._runs.get(run_id)
        if run is None:
            raise KeyError(run_id)
        return run

    async def start(self, dataset_id: str) -> BenchmarkRun:
        definition = self._definitions.get(dataset_id)
        if definition is None:
            raise KeyError(dataset_id)
        async with self._lock:
            if any(
                item.status in {"queued", "running"} for item in self._runs.values()
            ):
                raise RuntimeError("已有离线基准评测正在执行，请等待完成后再启动")
            dataset = self._read_dataset(definition)
            now = datetime.now(timezone.utc)
            run = BenchmarkRun(
                run_id=uuid.uuid4().hex,
                dataset_id=dataset.id,
                dataset_name=dataset.name,
                evaluation_type=dataset.evaluation_type,
                status="queued",
                case_count=dataset.case_count,
                created_at=now,
            )
            self._runs[run.run_id] = run
            self._persist(run)
            task = asyncio.create_task(self._execute(run.run_id, definition))
            self._tasks[run.run_id] = task
            task.add_done_callback(lambda _: self._tasks.pop(run.run_id, None))
            return run.model_copy(deep=True)

    def report_path(self, run_id: str, report_format: str) -> Path:
        run = self.get_run(run_id)
        name = (
            run.json_report_name if report_format == "json" else run.markdown_report_name
        )
        if not name:
            raise FileNotFoundError(report_format)
        run_dir = (self.report_root / run_id).resolve()
        path = (run_dir / name).resolve()
        if run_dir not in path.parents or not path.is_file():
            raise FileNotFoundError(report_format)
        return path

    async def _execute(
        self, run_id: str, definition: _DatasetDefinition
    ) -> None:
        run = self._runs[run_id]
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        self._persist(run)
        run_dir = self.report_root / run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        command = [
            sys.executable,
            str(definition.script_path),
            "--dataset",
            str(definition.dataset_path),
            "--output-dir",
            str(run_dir),
            *definition.extra_args,
        ]
        try:
            return_code, stdout, stderr = await self._command_runner(
                command, self.backend_dir
            )
            reports = sorted(run_dir.glob("*.json"), key=lambda item: item.stat().st_mtime)
            if return_code not in {0, 2} or not reports:
                detail = stderr.strip() or stdout.strip() or f"评测进程退出码：{return_code}"
                raise RuntimeError(detail[-2000:])
            json_path = reports[-1]
            payload = json.loads(json_path.read_text(encoding="utf-8"))
            acceptance = payload.get("acceptance")
            run.metrics = payload.get("metrics") or {}
            run.acceptance = acceptance if isinstance(acceptance, dict) else None
            if run.acceptance is None:
                run.status = "completed"
            else:
                run.status = "passed" if run.acceptance.get("passed") else "failed"
            run.json_report_name = json_path.name
            markdown_reports = sorted(
                run_dir.glob("*.md"), key=lambda item: item.stat().st_mtime
            )
            if markdown_reports:
                run.markdown_report_name = markdown_reports[-1].name
            run.stdout_summary = stdout.strip()[-4000:] or None
        except Exception as exc:
            run.status = "system_failed"
            run.error_message = f"{type(exc).__name__}: {exc}"[-2000:]
        finally:
            run.finished_at = datetime.now(timezone.utc)
            self._persist(run)

    async def _run_command(
        self, command: list[str], cwd: Path
    ) -> tuple[int, str, str]:
        # Windows 下 PyCharm/Uvicorn 可能运行不支持异步子进程的事件循环。
        # 在线程中使用同步 subprocess，既不阻塞 FastAPI 事件循环，也能跨平台启动脚本。
        def execute() -> tuple[int, str, str]:
            options: dict[str, Any] = {}
            if sys.platform == "win32":
                options["creationflags"] = subprocess.CREATE_NO_WINDOW
            completed = subprocess.run(
                command,
                cwd=str(cwd),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
                **options,
            )
            return completed.returncode, completed.stdout, completed.stderr

        return await asyncio.to_thread(execute)

    def _build_definitions(self) -> dict[str, _DatasetDefinition]:
        evaluation_dir = self.backend_dir / "evaluation"
        scripts_dir = self.backend_dir / "scripts"
        values = [
            _DatasetDefinition(
                id="anniversary-rule-retrieval-20260807",
                name="周年庆长规则知识召回",
                evaluation_type="retrieval",
                dataset_path=evaluation_dir / "knowledge_retrieval_cases.yaml",
                script_path=scripts_dir / "evaluate_knowledge_retrieval.py",
                extra_args=("--check-thresholds",),
            ),
            _DatasetDefinition(
                id="intent-hard-cases-20260803",
                name="多意图难例",
                evaluation_type="intent",
                dataset_path=evaluation_dir / "intent_hard_cases.yaml",
                script_path=scripts_dir / "evaluate_intents.py",
                extra_args=("--mode", "hybrid", "--check-thresholds"),
            ),
            _DatasetDefinition(
                id="semantic-cache-regression-20260806",
                name="语义缓存回归",
                evaluation_type="intent",
                dataset_path=evaluation_dir / "intent_cache_regression.yaml",
                script_path=scripts_dir / "evaluate_intents.py",
                extra_args=("--mode", "hybrid"),
            ),
        ]
        return {item.id: item for item in values}

    def _read_dataset(self, definition: _DatasetDefinition) -> BenchmarkDataset:
        with definition.dataset_path.open("r", encoding="utf-8") as file:
            payload = yaml.safe_load(file) or {}
        cases = payload.get("cases")
        if not isinstance(cases, list):
            raise ValueError(f"数据集缺少cases列表：{definition.id}")
        return BenchmarkDataset(
            id=definition.id,
            name=definition.name,
            description=str(payload.get("description") or ""),
            evaluation_type=definition.evaluation_type,
            case_count=len(cases),
            has_acceptance_thresholds=isinstance(
                payload.get("acceptance_thresholds"), dict
            ),
        )

    def _persist(self, run: BenchmarkRun) -> None:
        run_dir = self.report_root / run.run_id
        run_dir.mkdir(parents=True, exist_ok=True)
        path = run_dir / "run.json"
        temporary = run_dir / "run.json.tmp"
        temporary.write_text(
            json.dumps(run.model_dump(mode="json"), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(path)

    def _load_runs(self) -> dict[str, BenchmarkRun]:
        runs: dict[str, BenchmarkRun] = {}
        for path in self.report_root.glob("*/run.json"):
            try:
                run = BenchmarkRun.model_validate_json(path.read_text(encoding="utf-8"))
                if run.status in {"queued", "running"}:
                    run.status = "system_failed"
                    run.error_message = "Python服务重启，评测任务已中断"
                    run.finished_at = datetime.now(timezone.utc)
                runs[run.run_id] = run
            except (OSError, ValueError):
                continue
        return runs


def create_offline_benchmark_router(
    manager: OfflineBenchmarkManager | None = None,
) -> APIRouter:
    manager = manager or OfflineBenchmarkManager()
    router = APIRouter(
        prefix="/api/evaluation/benchmarks", tags=["offline-benchmark"]
    )

    @router.get("/datasets", response_model=list[BenchmarkDataset])
    async def list_datasets() -> list[BenchmarkDataset]:
        return manager.list_datasets()

    @router.get("/runs", response_model=list[BenchmarkRun])
    async def list_runs(limit: int = Query(default=20, ge=1, le=100)) -> list[BenchmarkRun]:
        return manager.list_runs(limit)

    @router.post("/runs", response_model=BenchmarkRun, status_code=202)
    async def start_run(payload: StartBenchmarkRequest) -> BenchmarkRun:
        try:
            return await manager.start(payload.dataset_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="离线评测数据集不存在") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/runs/{run_id}", response_model=BenchmarkRun)
    async def get_run(run_id: str) -> BenchmarkRun:
        try:
            return manager.get_run(run_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="离线评测任务不存在") from exc

    @router.get("/runs/{run_id}/report")
    async def download_report(
        run_id: str,
        report_format: Literal["json", "markdown"] = Query(default="json", alias="format"),
    ) -> FileResponse:
        try:
            path = manager.report_path(run_id, report_format)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="离线评测任务不存在") from exc
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="评测报告尚未生成") from exc
        media_type = "application/json" if report_format == "json" else "text/markdown"
        run = manager.get_run(run_id)
        return FileResponse(
            path,
            media_type=media_type,
            filename=report_download_name(run, report_format),
        )

    return router
