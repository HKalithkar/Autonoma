from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

_LOGGER = logging.getLogger("autonoma.otel")
_INITIALIZED = False


def init_otel(service_name: str) -> None:
    global _INITIALIZED
    if _INITIALIZED:
        return
    if os.getenv("OTEL_SDK_DISABLED", "false").lower() == "true":
        _LOGGER.info("otel_disabled service=%s", service_name)
        _INITIALIZED = True
        return

    resource_attrs: dict[str, Any] = {SERVICE_NAME: service_name}
    service_version = os.getenv("SERVICE_VERSION")
    if service_version:
        resource_attrs[SERVICE_VERSION] = service_version
    resource = Resource.create(resource_attrs)

    provider = TracerProvider(resource=resource)
    exporter_kwargs: dict[str, Any] = {}
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT")
    if not endpoint:
        _LOGGER.info("otel_skipped_missing_endpoint service=%s", service_name)
        _INITIALIZED = True
        return
    exporter_kwargs["endpoint"] = endpoint
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(**exporter_kwargs)))
    trace.set_tracer_provider(provider)

    HTTPXClientInstrumentor().instrument()
    _INITIALIZED = True


def instrument_fastapi(app: Any) -> None:
    if getattr(app.state, "otel_instrumented", False):
        return
    FastAPIInstrumentor().instrument_app(app)
    app.state.otel_instrumented = True
