#!/usr/bin/env python3
"""Load operator follow graph + discover preferences from JSON profile data.

Usage:
  make seed-profiles
  uv run --with httpx python scripts/seed_operator_profile.py --profile example --dry-run

Requires a running gateway (default http://localhost:8090) and applied DB migrations.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import httpx

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_GATEWAY = os.getenv("MAYA_GATEWAY_URL", "http://localhost:8090")
DEFAULT_OPERATOR = os.getenv("MAYA_OPERATOR_ID", "local")
PROFILE_DIR = REPO_ROOT / "packages" / "maya-db" / "migrations" / "data"


def _load_profile(name: str) -> dict[str, Any]:
    path = PROFILE_DIR / f"operator_profiles_{name}.json"
    if not path.is_file():
        raise FileNotFoundError(f"profile not found: {path}")
    return json.loads(path.read_text())


def _load_profile_file(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise FileNotFoundError(f"profile file not found: {path}")
    return json.loads(path.read_text())


class ProfileSeeder:
    def __init__(
        self,
        base_url: str,
        operator_id: str,
        *,
        dry_run: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.operator_id = operator_id
        self.dry_run = dry_run
        self._client: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ProfileSeeder:
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=60.0)
        return self

    async def __aexit__(self, *args: object) -> None:
        if self._client:
            await self._client.aclose()

    def _log(self, msg: str) -> None:
        print(msg)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: dict[str, Any] | None = None,
        expected: tuple[int, ...] = (200, 201),
    ) -> dict[str, Any] | None:
        if self.dry_run:
            self._log(f"[dry-run] {method} {path} {json_body or ''}")
            return None
        assert self._client is not None
        resp = await self._client.request(method, path, json=json_body)
        if resp.status_code not in expected:
            raise RuntimeError(f"{method} {path} -> {resp.status_code}: {resp.text}")
        if resp.content:
            return resp.json()
        return None

    async def find_person_by_slug(self, slug: str) -> dict[str, Any] | None:
        if self.dry_run:
            return None
        assert self._client is not None
        resp = await self._client.get(
            "/api/follow/tree",
            params={"operator_id": self.operator_id},
        )
        if resp.status_code != 200:
            raise RuntimeError(f"GET /api/follow/tree -> {resp.status_code}")
        for node in resp.json().get("nodes", []):
            person = node.get("person") or node
            if person.get("slug") == slug:
                return person
        return None

    async def ensure_person(self, spec: dict[str, Any]) -> str:
        slug = spec["slug"]
        existing = await self.find_person_by_slug(slug)
        if existing:
            self._log(f"person {slug} already exists ({existing['id']})")
            return str(existing["id"])
        body: dict[str, Any] = {
            "slug": slug,
            "display_name": spec["display_name"],
            "kind": spec.get("kind", "REAL"),
        }
        if spec.get("realm"):
            body["realm"] = spec["realm"]
        data = await self._request("POST", "/api/follow/persons", json_body=body)
        assert data is not None
        self._log(f"created person {slug} ({data['id']})")
        return str(data["id"])

    async def attach_channel(self, person_id: str, channel_input: str) -> None:
        await self._request(
            "POST",
            f"/api/follow/persons/{person_id}/channels",
            json_body={"resolve": {"input": channel_input}},
        )
        self._log(f"attached channel {channel_input} -> person {person_id}")

    async def follow_person(self, person_id: str, follow: dict[str, Any]) -> None:
        await self._request(
            "POST",
            "/api/follow/follows",
            json_body={
                "subject_type": "PERSON",
                "subject_id": person_id,
                "cadence": follow.get("cadence", "weekly"),
                "notify_homepage": follow.get("notify_homepage", True),
                "notify_discord": follow.get("notify_discord", True),
                "mpv_autolaunch": follow.get("mpv_autolaunch", False),
                "muted": follow.get("muted", False),
            },
        )
        self._log(f"followed person {person_id} cadence={follow.get('cadence', 'weekly')}")

    async def apply_preferences(self, prefs: dict[str, Any]) -> None:
        patch = {k: v for k, v in prefs.items() if v is not None}
        if not patch:
            return
        await self._request(
            "PATCH",
            f"/api/discover/preferences?operator_id={self.operator_id}",
            json_body=patch,
        )
        self._log(f"patched discover preferences for operator {self.operator_id}")


async def run_seed(
    profile: dict[str, Any],
    *,
    gateway_url: str,
    operator_id: str,
    dry_run: bool,
) -> None:
    if dry_run:
        print(f"seed profile (dry-run) operator={operator_id} gateway={gateway_url}")
        for person in profile.get("persons", []):
            print(f"  person: {person['slug']} channels={len(person.get('channels', []))}")
        if profile.get("preferences"):
            print(f"  preferences: {profile['preferences']}")
        return

    async with ProfileSeeder(gateway_url, operator_id, dry_run=dry_run) as seeder:
        for person_spec in profile.get("persons", []):
            person_id = await seeder.ensure_person(person_spec)
            for channel in person_spec.get("channels", []):
                await seeder.attach_channel(person_id, channel)
            follow = person_spec.get("follow")
            if follow:
                await seeder.follow_person(person_id, follow)

        prefs = profile.get("preferences")
        if prefs:
            await seeder.apply_preferences(prefs)

    print(f"Profile seed complete for operator {operator_id}.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed operator follow graph from JSON profile")
    parser.add_argument(
        "--profile",
        default="example",
        help="Profile name (loads operator_profiles_<name>.json from maya-db migrations/data)",
    )
    parser.add_argument(
        "--file",
        type=Path,
        help="Explicit path to profile JSON (overrides --profile)",
    )
    parser.add_argument(
        "--gateway-url",
        default=DEFAULT_GATEWAY,
        help=f"Gateway base URL (default: {DEFAULT_GATEWAY})",
    )
    parser.add_argument(
        "--operator-id",
        default=None,
        help=f"Operator id (default: profile default_operator_id or {DEFAULT_OPERATOR})",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print planned actions without calling the gateway",
    )
    args = parser.parse_args()

    try:
        if args.file:
            profile = _load_profile_file(args.file)
        else:
            profile = _load_profile(args.profile)
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(2)

    operator_id = (
        args.operator_id
        or profile.get("default_operator_id")
        or DEFAULT_OPERATOR
    )

    try:
        asyncio.run(
            run_seed(
                profile,
                gateway_url=args.gateway_url,
                operator_id=operator_id,
                dry_run=args.dry_run,
            )
        )
    except httpx.ConnectError as exc:
        print(f"gateway unreachable at {args.gateway_url}: {exc}", file=sys.stderr)
        sys.exit(1)
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
