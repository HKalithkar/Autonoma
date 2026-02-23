from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger("autonoma.runtime_orchestrator.temporal")


class TemporalStarter:
    """Starts Temporal workflows when configured; otherwise no-op."""

    def __init__(self, *, enabled: bool, address: str, task_queue: str) -> None:
        self._enabled = enabled
        self._address = address
        self._task_queue = task_queue

    def start_run_workflow(self, *, run_id: str, payload: dict[str, Any]) -> None:
        if not self._enabled:
            return
        try:
            asyncio.run(self._start_async(run_id=run_id, payload=payload))
        except RuntimeError:
            logger.warning("temporal_start_skipped reason=event_loop_running run_id=%s", run_id)
        except Exception as exc:
            logger.warning("temporal_start_failed run_id=%s error=%s", run_id, exc)

    async def _start_async(self, *, run_id: str, payload: dict[str, Any]) -> None:
        try:
            from temporalio.client import Client
        except Exception as exc:  # pragma: no cover
            logger.warning("temporal_client_unavailable error=%s", exc)
            return
        client = await Client.connect(self._address)
        await client.start_workflow(
            "runtime_run_workflow",
            payload,
            id=f"runtime-run-{run_id}",
            task_queue=self._task_queue,
        )
