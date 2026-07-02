"""Load repo .env; .env wins for OAuth/base URL keys over inherited shell env."""

from __future__ import annotations

import os
from pathlib import Path

# Shell exports (e.g. from direnv) must not block .env for these keys.
_DOTENV_OVERRIDE_KEYS = frozenset(
    {
        "MAYA_APP_BASE_URL",
        "MAYA_GATEWAY_URL",
        "MAYA_PUBLIC_URL",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REDIRECT_URI",
        "GOOGLE_LOGIN_REDIRECT_URI",
        "GOOGLE_CONNECT_REDIRECT_URI",
        "MAYA_OAUTH_DYNAMIC_REDIRECT",
    }
)


def load_env_files(*env_files: Path) -> None:
    for env_file in env_files:
        if not env_file.is_file():
            continue
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            if not key:
                continue
            if key in _DOTENV_OVERRIDE_KEYS or key not in os.environ:
                os.environ[key] = val.strip().strip('"').strip("'")
