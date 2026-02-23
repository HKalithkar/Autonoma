from __future__ import annotations

import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from libs.common.context import set_request_context


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        correlation_id = request.headers.get("x-correlation-id") or str(uuid.uuid4())
        actor_id = request.headers.get("x-actor-id") or "anonymous"
        tenant_id = request.headers.get("x-tenant-id") or "default"
        set_request_context(correlation_id=correlation_id, actor_id=actor_id, tenant_id=tenant_id)
        response = await call_next(request)
        response.headers["x-correlation-id"] = correlation_id
        return response
