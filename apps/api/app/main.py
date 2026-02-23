import logging
import os

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import CONTENT_TYPE_LATEST

from libs.common.metrics import render_metrics
from libs.common.otel import init_otel, instrument_fastapi

from .audit import audit_event
from .db import init_db
from .middleware import RequestContextMiddleware
from .routes import (
    admin,
    agent,
    approvals,
    audit,
    auth,
    chat,
    iam,
    plugins,
    policy,
    runs,
    runs_v1,
    secrets,
    workflows,
)
from .seed import seed_data

logging.basicConfig(level=logging.INFO)


def create_app() -> FastAPI:
    application = FastAPI(title="Autonoma API", version="0.0.0")
    init_otel(os.getenv("SERVICE_NAME", "api"))
    instrument_fastapi(application)
    application.add_middleware(RequestContextMiddleware)
    allow_origins = [
        origin.strip()
        for origin in os.getenv("CORS_ALLOW_ORIGINS", "").split(",")
        if origin.strip()
    ]
    if allow_origins:
        application.add_middleware(
            CORSMiddleware,
            allow_origins=allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["*"],
            max_age=600,
        )
    application.include_router(auth.router)
    application.include_router(admin.router)
    application.include_router(agent.router)
    application.include_router(audit.router)
    application.include_router(policy.router)
    application.include_router(iam.router)
    application.include_router(plugins.router)
    application.include_router(workflows.router)
    application.include_router(runs.router)
    application.include_router(runs_v1.router)
    application.include_router(approvals.router)
    application.include_router(secrets.router)
    application.include_router(chat.router)
    from .routes import memory

    application.include_router(memory.router)
    from .routes import events

    application.include_router(events.router)
    from .routes import gitops

    application.include_router(gitops.router)

    @application.on_event("startup")
    def startup() -> None:
        init_db()
        seed_data()

    @application.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @application.get("/readyz")
    def readyz() -> dict[str, str]:
        return {"status": "ready"}

    @application.get("/healthz/audit")
    def audit_health() -> dict[str, str]:
        audit_event("healthcheck", "allow", {"component": "api"})
        return {"status": "ok"}

    @application.get("/metrics")
    def metrics() -> Response:
        return Response(content=render_metrics(), media_type=CONTENT_TYPE_LATEST)

    return application


app = create_app()
