"""Permission groups mapped to Google OAuth scopes."""

from __future__ import annotations

LOGIN_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

CONNECT_BASE_SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
]

PERMISSION_GROUPS: dict[str, list[str]] = {
    "mailbox_read": [
        "https://www.googleapis.com/auth/gmail.readonly",
    ],
    "mailbox_send": [
        "https://www.googleapis.com/auth/gmail.compose",
        "https://www.googleapis.com/auth/gmail.send",
        "https://www.googleapis.com/auth/gmail.modify",
    ],
    "calendar_read": [
        "https://www.googleapis.com/auth/calendar.readonly",
    ],
    "calendar_write": [
        "https://www.googleapis.com/auth/calendar",
    ],
}

ALL_PERMISSION_GROUPS = tuple(PERMISSION_GROUPS.keys())


def scopes_for_permissions(permissions: list[str]) -> list[str]:
    scopes: list[str] = []
    seen: set[str] = set()
    for perm in permissions:
        for scope in PERMISSION_GROUPS.get(perm, []):
            if scope not in seen:
                seen.add(scope)
                scopes.append(scope)
    return scopes


def connect_scopes(permissions: list[str] | None = None) -> list[str]:
    perms = permissions or ["mailbox_read", "calendar_read"]
    merged = list(CONNECT_BASE_SCOPES)
    seen = set(merged)
    for scope in scopes_for_permissions(perms):
        if scope not in seen:
            seen.add(scope)
            merged.append(scope)
    return merged


def granted_permissions(granted_scopes: list[str]) -> dict[str, bool]:
    granted_set = set(granted_scopes or [])
    return {
        perm: all(scope in granted_set for scope in scopes)
        for perm, scopes in PERMISSION_GROUPS.items()
    }


def has_permission(granted_scopes: list[str], permission: str) -> bool:
    required = PERMISSION_GROUPS.get(permission, [])
    if not required:
        return False
    granted_set = set(granted_scopes or [])
    return all(scope in granted_set for scope in required)
