#!/usr/bin/env python3
"""Verify Google OAuth config and print Google Cloud Console checklist."""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.env_loader import load_env_files  # noqa: E402
from services.paths import VOICE_RUNTIME, setup_paths  # noqa: E402

setup_paths()
load_env_files(ROOT / ".env", VOICE_RUNTIME / ".env")


def _reload_config():
    import services.integrations.google.config as cfg

    return importlib.reload(cfg)


def _extract_redirect_uri(location: str) -> str | None:
    parsed = urllib.parse.urlparse(location)
    params = urllib.parse.parse_qs(parsed.query)
    values = params.get("redirect_uri")
    return values[0] if values else None


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify Google OAuth redirect configuration")
    parser.add_argument(
        "--base-url",
        default=os.getenv("MAYA_APP_BASE_URL", "http://localhost:8090").rstrip("/"),
        help="Gateway base URL to probe (default: MAYA_APP_BASE_URL)",
    )
    args = parser.parse_args()
    cfg = _reload_config()

    print("=== Google OAuth config ===")
    if not cfg.google_oauth_configured():
        print("ERROR: GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
        return 1

    print(f"Client ID:          {cfg.GOOGLE_CLIENT_ID}")
    print(f"App base URL:       {cfg.APP_BASE_URL}")
    print(f"Login redirect:     {cfg.GOOGLE_LOGIN_REDIRECT_URI}")
    print(f"Connect redirect:   {cfg.GOOGLE_CONNECT_REDIRECT_URI}")
    print(f"Dynamic redirect:   {cfg.dynamic_redirect_enabled()}")

    checklist = cfg.google_console_checklist()
    print("\n=== Register in Google Cloud Console ===")
    print(f"OAuth client ID: {cfg.GOOGLE_CLIENT_ID}\n")
    print("Authorized redirect URIs:")
    for uri in checklist["redirect_uris"]:
        print(f"  {uri}")
    print("\nAuthorized JavaScript origins:")
    for origin in checklist["javascript_origins"]:
        print(f"  {origin}")

    try:
        import http.client
        import urllib.parse

        parsed = urllib.parse.urlparse(f"{args.base_url}/api/platform/auth/login/google")
        conn_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        conn = conn_cls(parsed.netloc, timeout=10)
        path = parsed.path or "/"
        if parsed.query:
            path = f"{path}?{parsed.query}"
        conn.request("GET", path)
        resp = conn.getresponse()
        location = resp.getheader("Location", "")
        conn.close()
        live_redirect = _extract_redirect_uri(location)
        print("\n=== Live login probe ===")
        print(f"Probe URL:          {args.base_url}/api/platform/auth/login/google")
        if live_redirect:
            print(f"Live redirect_uri:  {live_redirect}")
            if live_redirect not in checklist["redirect_uris"]:
                print("WARN: live redirect_uri is not in the printed checklist — add it to Console")
        else:
            print("WARN: could not read redirect_uri from login redirect (is gateway running?)")
    except Exception as exc:
        print(f"\nWARN: live probe failed ({exc})")

    print("\nNext: delete any empty URI rows in Console, Save, wait ~1 min, retry in incognito.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
