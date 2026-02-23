from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

logger = logging.getLogger("autonoma.runtime_orchestrator.event_bus")


class JetStreamPublisher:
    """Publishes canonical runtime events to NATS JetStream when enabled."""

    def __init__(
        self, *, enabled: bool, nats_url: str, subject: str, stream_name: str
    ) -> None:
        self._enabled = enabled
        self._nats_url = nats_url
        self._subject = subject
        self._stream_name = stream_name

    def publish(self, event: dict[str, Any]) -> None:
        if not self._enabled:
            return
        try:
            asyncio.run(self._publish_async(event))
        except RuntimeError:
            # If already inside an event loop, we degrade to a safe no-op.
            logger.warning("jetstream_publish_skipped reason=event_loop_running")
        except Exception as exc:
            logger.warning("jetstream_publish_failed error=%s", exc)

    async def _publish_async(self, event: dict[str, Any]) -> None:
        try:
            from nats.aio.client import Client as NATS
        except Exception as exc:  # pragma: no cover
            logger.warning("jetstream_client_unavailable error=%s", exc)
            return
        nc = NATS()
        await nc.connect(servers=[self._nats_url], connect_timeout=1)
        try:
            js = nc.jetstream()
            await self._ensure_stream(js)
            await js.publish(self._subject, json.dumps(event).encode("utf-8"))
        finally:
            await nc.drain()

    async def _ensure_stream(self, js: Any) -> None:
        try:
            info = await js.stream_info(self._stream_name)
            subjects = list(getattr(getattr(info, "config", None), "subjects", []) or [])
            if self._subject not in subjects:
                await js.update_stream(
                    name=self._stream_name, subjects=subjects + [self._subject]
                )
            return
        except Exception as exc:
            if "not found" not in str(exc).lower():
                logger.warning("jetstream_stream_info_failed error=%s", exc)

        try:
            await js.add_stream(name=self._stream_name, subjects=[self._subject])
        except Exception as exc:
            logger.warning("jetstream_stream_create_failed error=%s", exc)
