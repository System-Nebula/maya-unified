"""Google OAuth configuration."""

from __future__ import annotations

import os
from urllib.parse import urlparse

LOGIN_CALLBACK_PATH = "/auth/google/callback"
CONNECT_CALLBACK_PATH = "/api/integrations/google/callback"
API_LOGIN_CALLBACK_PATH = "/api/platform/auth/callback/google"


def _app_base_url() -> str:
    for key in ("MAYA_APP_BASE_URL", "MAYA_GATEWAY_URL", "MAYA_PUBLIC_URL"):
        value = os.getenv(key, "").strip().rstrip("/")
        if value:
            return value
    return "http://localhost:8090"


APP_BASE_URL = _app_base_url()

GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()

_legacy_login_redirect = os.getenv("GOOGLE_REDIRECT_URI", "").strip()
_default_login_redirect = f"{APP_BASE_URL}{API_LOGIN_CALLBACK_PATH}"

GOOGLE_LOGIN_REDIRECT_URI = (
    os.getenv("GOOGLE_LOGIN_REDIRECT_URI", "").strip()
    or _legacy_login_redirect
    or _default_login_redirect
)
GOOGLE_CONNECT_REDIRECT_URI = (
    os.getenv("GOOGLE_CONNECT_REDIRECT_URI", "").strip()
    or f"{APP_BASE_URL}{CONNECT_CALLBACK_PATH}"
)

MAYA_GOOGLE_TOKEN_DIR = os.getenv("MAYA_GOOGLE_TOKEN_DIR", ".data/google-tokens")


def dynamic_redirect_enabled() -> bool:
    return os.getenv("MAYA_OAUTH_DYNAMIC_REDIRECT", "1").lower() in ("1", "true", "yes")


def _port_from_base_url() -> int:
    parsed = urlparse(APP_BASE_URL)
    if parsed.port:
        return parsed.port
    return 443 if parsed.scheme == "https" else 80


def google_console_checklist(port: int | None = None) -> dict[str, list[str]]:
    """URIs and JS origins to register in Google Cloud Console."""
    port = port or _port_from_base_url()
    redirect_uris: list[str] = []
    javascript_origins: list[str] = []
    for host in ("localhost", "127.0.0.1"):
        base = f"http://{host}:{port}"
        javascript_origins.append(base)
        redirect_uris.extend(
            [
                f"{base}{LOGIN_CALLBACK_PATH}",
                f"{base}{API_LOGIN_CALLBACK_PATH}",
                f"{base}{CONNECT_CALLBACK_PATH}",
            ]
        )
    return {
        "redirect_uris": redirect_uris,
        "javascript_origins": javascript_origins,
    }


def redirect_uri_for_request(request, *, flow: str) -> str:
    """Resolve redirect URI for this OAuth flow, optionally from the browser host."""
    if flow == "login":
        static = GOOGLE_LOGIN_REDIRECT_URI
        path = LOGIN_CALLBACK_PATH
    elif flow == "connect":
        static = GOOGLE_CONNECT_REDIRECT_URI
        path = CONNECT_CALLBACK_PATH
    else:
        raise ValueError(f"unknown OAuth flow: {flow}")

    if not dynamic_redirect_enabled():
        return static

    host = (request.headers.get("host") or request.url.netloc or "").strip()
    scheme = request.url.scheme or "http"
    if not host:
        return static
    return f"{scheme}://{host}{path}"


def google_oauth_configured() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET)
