from __future__ import annotations

import hashlib
import os
import secrets
import time
from collections import defaultdict

from fastapi import APIRouter, HTTPException, Request, status
from fastapi.responses import RedirectResponse, Response

from ..audit import audit_event
from ..auth import (
    build_auth_url_for_host,
    exchange_code,
    exchange_refresh,
    generate_code_verifier,
    generate_state,
    get_settings,
    revoke_token,
)
from ..rbac import require_permission

router = APIRouter(prefix="/v1/auth", tags=["auth"])

_REFRESH_ATTEMPTS: dict[str, list[float]] = defaultdict(list)
_REFRESH_MAX = int(float(os.getenv("AUTH_REFRESH_RATE_LIMIT_MAX", "6")))
_REFRESH_WINDOW = int(float(os.getenv("AUTH_REFRESH_RATE_LIMIT_WINDOW", "60")))


def _refresh_rate_limited(key: str) -> bool:
    now = time.time()
    window_start = now - _REFRESH_WINDOW
    attempts = [ts for ts in _REFRESH_ATTEMPTS.get(key, []) if ts >= window_start]
    attempts.append(now)
    _REFRESH_ATTEMPTS[key] = attempts
    return len(attempts) > _REFRESH_MAX


@router.get("/login")
def login(request: Request) -> RedirectResponse:
    settings = get_settings()
    state = generate_state()
    verifier = generate_code_verifier()
    redirect_url = build_auth_url_for_host(settings, state, verifier, request.headers.get("host"))
    redirect = RedirectResponse(url=redirect_url, status_code=status.HTTP_302_FOUND)
    redirect.set_cookie(
        "oidc_state",
        state,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=600,
    )
    redirect.set_cookie(
        "oidc_code_verifier",
        verifier,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=600,
    )
    return redirect


@router.get("/callback")
def callback(request: Request) -> RedirectResponse:
    settings = get_settings()
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    if not code or not state:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing code or state")

    stored_state = request.cookies.get("oidc_state")
    verifier = request.cookies.get("oidc_code_verifier")
    if not stored_state or stored_state != state or not verifier:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid state")

    token_response = exchange_code(settings, code, verifier)
    access_token = token_response.get("access_token")
    refresh_token = token_response.get("refresh_token")
    if not access_token:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Missing access token")

    redirect_target = settings.ui_base_url.rstrip("/") + "/" if settings.ui_base_url else "/"
    redirect = RedirectResponse(url=redirect_target, status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie("oidc_state")
    redirect.delete_cookie("oidc_code_verifier")
    redirect.set_cookie(
        "autonoma_access_token",
        access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=token_response.get("expires_in", 3600),
    )
    if refresh_token:
        refresh_expires_in = token_response.get("refresh_expires_in", 2592000)
        refresh_max_age = int(float(os.getenv("AUTH_REFRESH_MAX_AGE", refresh_expires_in)))
        redirect.set_cookie(
            "autonoma_refresh_token",
            refresh_token,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=refresh_max_age,
        )
        redirect.set_cookie(
            "autonoma_csrf",
            secrets.token_urlsafe(32),
            httponly=False,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=refresh_max_age,
        )
    return redirect


@router.post("/logout")
def logout(request: Request) -> RedirectResponse:
    settings = get_settings()
    refresh_token = request.cookies.get("autonoma_refresh_token")
    if refresh_token:
        try:
            revoke_token(settings, refresh_token)
        except Exception:
            audit_event("authn", "deny", {"reason": "refresh_revoke_failed"})
    redirect = RedirectResponse(url="/", status_code=status.HTTP_302_FOUND)
    redirect.delete_cookie("autonoma_access_token")
    redirect.delete_cookie("autonoma_refresh_token")
    redirect.delete_cookie("autonoma_csrf")
    return redirect


@router.post("/refresh")
def refresh(request: Request) -> Response:
    settings = get_settings()
    refresh_token = request.cookies.get("autonoma_refresh_token")
    if not refresh_token:
        audit_event("authn", "deny", {"reason": "missing_refresh_token"})
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing refresh token",
        )
    csrf_cookie = request.cookies.get("autonoma_csrf")
    csrf_header = request.headers.get("x-csrf-token")
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        audit_event("authn", "deny", {"reason": "csrf_mismatch"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="CSRF check failed")
    try:
        refresh_fingerprint = hashlib.sha256(refresh_token.encode("utf-8")).hexdigest()
    except Exception:
        refresh_fingerprint = secrets.token_hex(8)
    client_host = request.client.host if request.client else "unknown"
    rate_key = f"{client_host}:{refresh_fingerprint}"
    if _refresh_rate_limited(rate_key):
        audit_event("authn", "deny", {"reason": "refresh_rate_limited"})
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many refresh attempts",
        )

    try:
        token_response = exchange_refresh(settings, refresh_token)
    except Exception:
        audit_event("authn", "deny", {"reason": "refresh_failed"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh failed")

    access_token = token_response.get("access_token")
    if not access_token:
        audit_event("authn", "deny", {"reason": "missing_access_token"})
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh failed")

    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.set_cookie(
        "autonoma_access_token",
        access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite=settings.cookie_samesite,
        max_age=token_response.get("expires_in", 3600),
    )
    new_refresh = token_response.get("refresh_token")
    if new_refresh:
        refresh_expires_in = token_response.get("refresh_expires_in", 2592000)
        refresh_max_age = int(float(os.getenv("AUTH_REFRESH_MAX_AGE", refresh_expires_in)))
        response.set_cookie(
            "autonoma_refresh_token",
            new_refresh,
            httponly=True,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=refresh_max_age,
        )
        response.set_cookie(
            "autonoma_csrf",
            secrets.token_urlsafe(32),
            httponly=False,
            secure=settings.cookie_secure,
            samesite=settings.cookie_samesite,
            max_age=refresh_max_age,
        )
    audit_event("authn", "allow", {"reason": "refresh"})
    return response


@router.get("/me")
def me(ctx=require_permission("auth:me")) -> dict[str, object]:
    return {
        "actor_id": ctx.actor_id,
        "username": ctx.username,
        "tenant_id": ctx.tenant_id,
        "roles": ctx.roles,
        "permissions": ctx.permissions,
    }
