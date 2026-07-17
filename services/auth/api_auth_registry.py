"""Deny-by-default API authorization registry (SEC-002).

Route-level ``Depends`` remain authoritative. Gateway middleware uses this
registry so unclassified ``/api`` routes require an operator session instead of
falling open when a prefix was omitted from an allowlist.

Public and room-member entries must be exact ``(METHOD, path_template)`` pairs
with a documented reason. Everything else defaults to operator (or admin for
``/api/admin…``). ``service`` soft-attaches a session and leaves auth to the
route (e.g. browser capture token).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Iterable

from starlette.routing import Match


class ApiAuthClass(str, Enum):
    PUBLIC = "public"
    ROOM_MEMBER = "room_member"
    OPERATOR = "operator"
    ADMIN = "admin"
    SERVICE = "service"


@dataclass(frozen=True)
class ApiAuthEntry:
    method: str
    path: str
    auth_class: ApiAuthClass
    reason: str

    @property
    def key(self) -> tuple[str, str]:
        return self.method.upper(), self.path


# Explicit exceptions to the operator default. Keep reasons short and testable.
_EXPLICIT_ENTRIES: tuple[ApiAuthEntry, ...] = (
    ApiAuthEntry(
        "GET",
        "/api/auth/me",
        ApiAuthClass.PUBLIC,
        "Bootstrap/session probe; returns unauthenticated payload without cookie",
    ),
    ApiAuthEntry(
        "POST",
        "/api/auth/login",
        ApiAuthClass.PUBLIC,
        "Operator login",
    ),
    ApiAuthEntry(
        "POST",
        "/api/auth/logout",
        ApiAuthClass.PUBLIC,
        "Clear session cookie",
    ),
    ApiAuthEntry(
        "POST",
        "/api/operators",
        ApiAuthClass.PUBLIC,
        "First-run operator bootstrap (handler enforces empty-operator guard)",
    ),
    ApiAuthEntry(
        "GET",
        "/api/integrations/google/callback",
        ApiAuthClass.PUBLIC,
        "OAuth redirect callback; validated by state/code exchange",
    ),
    ApiAuthEntry(
        "GET",
        "/api/imagine/health",
        ApiAuthClass.PUBLIC,
        "Imagine worker liveness probe",
    ),
    ApiAuthEntry(
        "GET",
        "/api/platform/auth/status",
        ApiAuthClass.PUBLIC,
        "Platform auth availability probe (operator profile mounts only)",
    ),
    ApiAuthEntry(
        "GET",
        "/api/platform/auth/login/{provider}",
        ApiAuthClass.PUBLIC,
        "Platform OAuth login start (operator profile mounts only)",
    ),
    ApiAuthEntry(
        "GET",
        "/api/platform/auth/callback/google",
        ApiAuthClass.PUBLIC,
        "Platform Google OAuth callback",
    ),
    ApiAuthEntry(
        "GET",
        "/api/rooms/{slug}",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room info; room membership cookie enforced in handler",
    ),
    ApiAuthEntry(
        "POST",
        "/api/rooms/{slug}/join",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room join",
    ),
    ApiAuthEntry(
        "POST",
        "/api/rooms/{slug}/chat",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room chat",
    ),
    ApiAuthEntry(
        "GET",
        "/api/rooms/{slug}/messages",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room message history",
    ),
    ApiAuthEntry(
        "GET",
        "/api/rooms/{slug}/events",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room SSE/events",
    ),
    ApiAuthEntry(
        "POST",
        "/api/rooms/{slug}/leave",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room leave",
    ),
    ApiAuthEntry(
        "GET",
        "/api/rooms/{slug}/queue",
        ApiAuthClass.ROOM_MEMBER,
        "Guest room queue status",
    ),
    ApiAuthEntry(
        "POST",
        "/api/rooms/{slug}/queue/request",
        ApiAuthClass.ROOM_MEMBER,
        "Guest queue request",
    ),
    ApiAuthEntry(
        "POST",
        "/api/rooms/{slug}/queue/release",
        ApiAuthClass.ROOM_MEMBER,
        "Guest queue release",
    ),
    ApiAuthEntry(
        "POST",
        "/api/browser/capture",
        ApiAuthClass.SERVICE,
        "Browser capture token or operator session (require_browser_capture)",
    ),
    ApiAuthEntry(
        "POST",
        "/api/discover/inbox/webhook",
        ApiAuthClass.SERVICE,
        "Mailgun HMAC signature is verified by the webhook handler",
    ),
)

_EXPLICIT: dict[tuple[str, str], ApiAuthEntry] = {e.key: e for e in _EXPLICIT_ENTRIES}


def explicit_entries() -> tuple[ApiAuthEntry, ...]:
    return _EXPLICIT_ENTRIES


def default_auth_class(path_template: str) -> ApiAuthClass:
    if path_template.startswith("/api/admin"):
        return ApiAuthClass.ADMIN
    return ApiAuthClass.OPERATOR


def classify_route(method: str, path_template: str) -> ApiAuthClass:
    """Classify a mounted FastAPI path template."""
    key = (method.upper(), path_template)
    entry = _EXPLICIT.get(key)
    if entry is not None:
        return entry.auth_class
    return default_auth_class(path_template)


def public_route_keys() -> frozenset[tuple[str, str]]:
    return frozenset(e.key for e in _EXPLICIT_ENTRIES if e.auth_class is ApiAuthClass.PUBLIC)


def _iter_http_routes(routes: Iterable[Any]) -> Iterable[Any]:
    for route in routes:
        nested = getattr(route, "routes", None)
        if nested is not None:
            yield from _iter_http_routes(nested)
            continue
        methods = getattr(route, "methods", None)
        path = getattr(route, "path", None)
        if not methods or not path:
            continue
        yield route


def iter_mounted_api_routes(app: Any) -> list[tuple[str, str]]:
    """Return sorted ``(METHOD, path_template)`` for mounted HTTP ``/api`` routes."""
    rows: list[tuple[str, str]] = []
    for route in _iter_http_routes(app.router.routes):
        path = route.path
        if not str(path).startswith("/api"):
            continue
        for method in sorted(route.methods):
            if method in {"HEAD", "OPTIONS"}:
                continue
            rows.append((method, path))
    rows.sort()
    return rows


def _http_scope(method: str, path: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method.upper(),
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 0),
        "server": ("127.0.0.1", 80),
    }


def match_api_route(app: Any, method: str, path: str) -> tuple[str, str] | None:
    """Match a live request to ``(METHOD, path_template)`` or ``None`` if unmatched."""
    if not path.startswith("/api"):
        return None
    scope = _http_scope(method, path)
    for route in _iter_http_routes(app.router.routes):
        match, _child = route.matches(scope)
        if match != Match.FULL:
            continue
        methods = route.methods or set()
        m = method.upper()
        if m not in methods and m not in {x.upper() for x in methods}:
            continue
        return m, route.path
    return None


def classify_request(app: Any, method: str, path: str) -> ApiAuthClass | None:
    """Return auth class for a live ``/api`` request, or ``None`` if no route matches."""
    matched = match_api_route(app, method, path)
    if matched is None:
        return None
    return classify_route(matched[0], matched[1])
