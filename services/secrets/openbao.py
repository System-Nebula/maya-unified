"""OpenBao KV v2 reader for local/dev secrets.

Matches the ``lib.portal.openbao._read_secret`` contract used by Ideogram:
pass the KV v2 API path (``secret/data/maya/...``) and get the inner data dict.

Resolution at call sites is still explicit > env > OpenBao. This module never
prints secret values. Empty ``BAO_ADDR`` / ``BAO_TOKEN`` (GitHub/Cursor blanks)
are treated as unset.
"""

from __future__ import annotations

import json
import os
import shlex
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from services.paths import DATA_DIR, ROOT

SLSKD_SECRET_PATH = "secret/data/maya/integrations/slskd"
IDEOGRAM_SECRET_PATH = "secret/data/maya/providers/ideogram"
DEFAULT_BAO_ADDR = "http://127.0.0.1:8200"
EXAMPLE_SLSKD_USERNAME = "maya-dev-example"
EXAMPLE_SLSKD_API_KEY = "ci-cloud-agent-slskd-key"
DEV_SEED_EXAMPLE = ROOT / "examples" / "openbao" / "dev-seed.json"
DEV_SEED_LOCAL = DATA_DIR / "openbao" / "dev-seed.json"


def _env(name: str) -> str:
    return (os.environ.get(name) or "").strip()


def bao_addr() -> str:
    return (_env("BAO_ADDR") or _env("VAULT_ADDR") or DEFAULT_BAO_ADDR).rstrip("/")


def bao_token() -> str:
    return _env("BAO_TOKEN") or _env("VAULT_TOKEN")


def bao_is_local(addr: str | None = None) -> bool:
    host = urllib.parse.urlparse(addr or bao_addr()).hostname or ""
    return host in {"127.0.0.1", "localhost", "::1"}


def _request(
    path: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    timeout: float = 3.0,
) -> dict[str, Any]:
    token = bao_token()
    if not token:
        raise RuntimeError("BAO_TOKEN (or VAULT_TOKEN) is required")
    url = f"{bao_addr()}/v1/{path.lstrip('/')}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"X-Vault-Token": token, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read()
    if not raw:
        return {}
    payload = json.loads(raw.decode("utf-8"))
    return payload if isinstance(payload, dict) else {}


def read_secret(path: str, *, timeout: float = 3.0) -> dict[str, Any]:
    """Return KV v2 ``data.data`` for an API path such as ``secret/data/maya/...``."""
    if not bao_token():
        return {}
    try:
        payload = _request(path, method="GET", timeout=timeout)
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, RuntimeError):
        return {}
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return {}
    inner = data.get("data") if isinstance(data.get("data"), dict) else data
    return dict(inner) if isinstance(inner, dict) else {}


def _read_secret(path: str) -> dict[str, Any]:
    """Alias for ``lib.portal.openbao._read_secret``."""
    return read_secret(path)


def write_secret(path: str, data: dict[str, Any], *, timeout: float = 5.0) -> None:
    """KV v2 write. ``path`` is ``secret/data/...``."""
    _request(path, method="POST", body={"data": data}, timeout=timeout)


def slskd_credentials() -> dict[str, str]:
    """Soulseek login + optional API key from OpenBao (empty strings if missing)."""
    secret = read_secret(SLSKD_SECRET_PATH)
    username = str(
        secret.get("username")
        or secret.get("SLSKD_SLSK_USERNAME")
        or secret.get("SLSK_USERNAME")
        or ""
    )
    password = str(
        secret.get("password")
        or secret.get("SLSKD_SLSK_PASSWORD")
        or secret.get("SLSK_PASSWORD")
        or ""
    )
    api_key = str(secret.get("api_key") or secret.get("SLSKD_API_KEY") or "")
    network = str(secret.get("network") or "")
    return {
        "username": username,
        "password": password,
        "api_key": api_key,
        "network": network,
    }


def _env_slskd() -> dict[str, str]:
    username = _env("SLSKD_SLSK_USERNAME") or _env("SLSK_USERNAME")
    password = _env("SLSKD_SLSK_PASSWORD") or _env("SLSK_PASSWORD")
    api_key = _env("SLSKD_API_KEY")
    return {"username": username, "password": password, "api_key": api_key}


def is_example_slskd_account(secret: dict[str, Any] | None = None) -> bool:
    """True for the bundled mock account (not a Soulseek network login)."""
    if _env("SLSKD_EXAMPLE").lower() in {"1", "true", "yes"}:
        return True
    data = secret if secret is not None else read_secret(SLSKD_SECRET_PATH)
    username = str(data.get("username") or "")
    network = str(data.get("network") or "").lower()
    if _env("SLSKD_SLSK_USERNAME") and _env("SLSKD_SLSK_USERNAME") != EXAMPLE_SLSKD_USERNAME:
        return False
    return network == "example" or username == EXAMPLE_SLSKD_USERNAME


def load_dev_seed(path: Path | None = None) -> dict[str, dict[str, Any]]:
    """Return ``{kv_api_path: data}`` from a seed JSON file."""
    target = path or DEV_SEED_LOCAL
    if not target.is_file():
        return {}
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    secrets = payload.get("secrets") if isinstance(payload, dict) else None
    if not isinstance(secrets, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for kv_path, data in secrets.items():
        if isinstance(kv_path, str) and isinstance(data, dict):
            out[kv_path] = dict(data)
    return out


def ensure_local_dev_seed() -> Path:
    """Copy the bundled example seed into ``data/`` once (like voices/personalities)."""
    DEV_SEED_LOCAL.parent.mkdir(parents=True, exist_ok=True)
    if not DEV_SEED_LOCAL.is_file():
        DEV_SEED_LOCAL.write_text(DEV_SEED_EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
        try:
            DEV_SEED_LOCAL.chmod(0o600)
        except OSError:
            pass
    return DEV_SEED_LOCAL


def init_dev() -> str:
    """Seed local OpenBao from ``data/openbao/dev-seed.json`` (example on first run).

    Remote OpenBao is never overwritten with the bundled example account.
    Env Soulseek creds still win when the KV path is empty.
    """
    if not bao_token():
        return "openbao token missing; skip init-dev"
    if not bao_is_local():
        return seed_slskd_from_env()
    env_status = seed_slskd_from_env()
    if env_status.startswith("seeded") or "already present" in env_status:
        return env_status
    ensure_local_dev_seed()
    secrets = load_dev_seed(DEV_SEED_LOCAL)
    if not secrets:
        return "openbao dev seed missing or empty"
    written = 0
    for kv_path, data in secrets.items():
        write_secret(kv_path, data)
        written += 1
    if is_example_slskd_account(secrets.get(SLSKD_SECRET_PATH) or {}):
        return f"seeded {written} openbao path(s) from bundled example test account"
    return f"seeded {written} openbao path(s) from data/openbao/dev-seed.json"


def seed_slskd_from_env() -> str:
    """Copy env Soulseek creds into OpenBao only when the KV path is empty.

    Status text never includes secret values. Env still wins at read time.
    """
    if not bao_token():
        return "openbao token missing; skip slskd seed"
    existing = slskd_credentials()
    if existing["username"] and existing["password"]:
        return "openbao slskd secret already present"
    env_creds = _env_slskd()
    if not env_creds["username"] or not env_creds["password"]:
        return (
            "openbao slskd secret missing; "
            "bao kv put secret/maya/integrations/slskd username=... password=..."
        )
    payload = {"username": env_creds["username"], "password": env_creds["password"]}
    if len(env_creds["api_key"]) >= 16:
        payload["api_key"] = env_creds["api_key"]
    write_secret(SLSKD_SECRET_PATH, payload)
    return "seeded openbao slskd secret from environment"


def export_slskd_shell() -> str:
    """POSIX export lines for start scripts. Env already set wins."""
    creds = slskd_credentials()
    lines: list[str] = []
    if not _env("SLSKD_SLSK_USERNAME") and creds["username"]:
        lines.append(f"export SLSKD_SLSK_USERNAME={shlex.quote(creds['username'])}")
    if not _env("SLSKD_SLSK_PASSWORD") and creds["password"]:
        lines.append(f"export SLSKD_SLSK_PASSWORD={shlex.quote(creds['password'])}")
    if not _env("SLSKD_API_KEY") and len(creds["api_key"]) >= 16:
        lines.append(f"export SLSKD_API_KEY={shlex.quote(creds['api_key'])}")
    if is_example_slskd_account(creds):
        lines.append("export SLSKD_EXAMPLE=1")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "init-dev":
        print(init_dev())
    elif len(sys.argv) > 1 and sys.argv[1] == "seed":
        print(seed_slskd_from_env())
    else:
        print(export_slskd_shell())
