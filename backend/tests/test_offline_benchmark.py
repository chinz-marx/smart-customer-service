from __future__ import annotations

import asyncio
import json
import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.evaluation.offline_benchmark import (
    OfflineBenchmarkManager,
    create_offline_benchmark_router,
)
from app.evaluation import offline_benchmark


BACKEND_DIR = Path(__file__).resolve().parents[1]


def test_dataset_catalog_reads_real_yaml_counts(tmp_path: Path) -> None:
    manager = OfflineBenchmarkManager(
        backend_dir=BACKEND_DIR,
        report_root=tmp_path / "reports",
    )

    datasets = {item.id: item for item in manager.list_datasets()}

    assert datasets["anniversary-rule-retrieval-20260807"].case_count == 36
    assert datasets["intent-hard-cases-20260803"].case_count == 90
    assert datasets["semantic-cache-regression-20260806"].case_count == 45
    assert datasets["intent-hard-cases-20260803"].has_acceptance_thresholds is True


def test_dataset_catalog_api_only_exposes_whitelist(tmp_path: Path) -> None:
    manager = OfflineBenchmarkManager(
        backend_dir=BACKEND_DIR,
        report_root=tmp_path / "reports",
    )
    app = FastAPI()
    app.include_router(create_offline_benchmark_router(manager))

    with TestClient(app) as client:
        response = client.get("/api/evaluation/benchmarks/datasets")
        missing = client.post(
            "/api/evaluation/benchmarks/runs",
            json={"dataset_id": "../../arbitrary-script"},
        )

    assert response.status_code == 200
    assert {item["id"] for item in response.json()} == {
        "anniversary-rule-retrieval-20260807",
        "intent-hard-cases-20260803",
        "semantic-cache-regression-20260806",
    }
    assert missing.status_code == 404


def test_start_runs_whitelisted_script_and_persists_report(tmp_path: Path) -> None:
    commands: list[list[str]] = []

    async def fake_runner(command: list[str], cwd: Path) -> tuple[int, str, str]:
        commands.append(command)
        output_dir = Path(command[command.index("--output-dir") + 1])
        report = {
            "metrics": {"total_cases": 90, "intent_accuracy": 0.96},
            "acceptance": {"passed": True, "failures": []},
        }
        (output_dir / "intent-evaluation-test.json").write_text(
            json.dumps(report), encoding="utf-8"
        )
        (output_dir / "intent-evaluation-test.md").write_text(
            "# report", encoding="utf-8"
        )
        return 0, "评测完成", ""

    async def scenario() -> None:
        manager = OfflineBenchmarkManager(
            backend_dir=BACKEND_DIR,
            report_root=tmp_path / "reports",
            command_runner=fake_runner,
        )
        created = await manager.start("intent-hard-cases-20260803")
        await manager._tasks[created.run_id]
        finished = manager.get_run(created.run_id)

        assert finished.status == "passed"
        assert finished.metrics["intent_accuracy"] == 0.96
        assert manager.report_path(created.run_id, "json").is_file()
        assert "evaluate_intents.py" in " ".join(commands[0])
        assert "--check-thresholds" in commands[0]

    asyncio.run(scenario())


def test_only_one_benchmark_can_run_at_a_time(tmp_path: Path) -> None:
    gate = asyncio.Event()

    async def slow_runner(command: list[str], cwd: Path) -> tuple[int, str, str]:
        await gate.wait()
        return 1, "", "stopped"

    async def scenario() -> None:
        manager = OfflineBenchmarkManager(
            backend_dir=BACKEND_DIR,
            report_root=tmp_path / "reports",
            command_runner=slow_runner,
        )
        first = await manager.start("anniversary-rule-retrieval-20260807")
        try:
            await manager.start("intent-hard-cases-20260803")
        except RuntimeError as exc:
            assert "正在执行" in str(exc)
        else:
            raise AssertionError("并发评测应被拒绝")
        gate.set()
        await manager._tasks[first.run_id]

    asyncio.run(scenario())


def test_default_runner_uses_worker_thread_instead_of_async_subprocess(
    tmp_path: Path, monkeypatch,
) -> None:
    main_thread_id = threading.get_ident()
    worker_thread_ids: list[int] = []

    def fake_run(command, **kwargs):
        worker_thread_ids.append(threading.get_ident())
        return subprocess.CompletedProcess(command, 0, "完成", "")

    monkeypatch.setattr(offline_benchmark.subprocess, "run", fake_run)
    manager = OfflineBenchmarkManager(
        backend_dir=BACKEND_DIR,
        report_root=tmp_path / "reports",
    )

    result = asyncio.run(manager._run_command(["python", "evaluation.py"], BACKEND_DIR))

    assert result == (0, "完成", "")
    assert worker_thread_ids and worker_thread_ids[0] != main_thread_id
