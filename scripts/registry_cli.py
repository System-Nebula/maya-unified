#!/usr/bin/env python3
"""CLI for querying the model registry."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys

import httpx

DEFAULT_BASE = os.environ.get("MAYA_GATEWAY_URL", "http://localhost:8080")


def get(path: str, params: dict | None = None) -> dict:
    url = f"{DEFAULT_BASE}{path}"
    r = httpx.get(url, params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def post(path: str, payload: dict) -> dict:
    url = f"{DEFAULT_BASE}{path}"
    r = httpx.post(url, json=payload, timeout=30)
    r.raise_for_status()
    return r.json()


def list_releases(status: str | None, limit: int) -> None:
    params = {"limit": limit}
    if status:
        params["status"] = status
    data = get("/api/registry/releases", params)
    for item in data.get("items", []):
        print(f"{item['id'][:8]}  {item['slug']:48}  {item['capability_family']:20}  {item['eval_status']}")
    print(f"# total: {data['total']}", file=sys.stderr)


def show_release(release_id: str) -> None:
    data = get(f"/api/registry/releases/{release_id}")
    print(json.dumps(data, indent=2, default=str))


def list_evals(release_id: str | None, limit: int) -> None:
    params = {"limit": limit}
    if release_id:
        params["model_release_id"] = release_id
    data = get("/api/registry/evals", params)
    for item in data.get("items", []):
        print(f"{item['id'][:8]}  {item['model_release_id'][:8]}  {item['eval_suite']:24}  {item['eval_type']:16}  {item['status']}")
    print(f"# total: {data['total']}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Maya model registry CLI")
    parser.add_argument("--base", default=DEFAULT_BASE, help="Gateway base URL")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List model releases")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--limit", type=int, default=20)

    p_show = sub.add_parser("show", help="Show release details")
    p_show.add_argument("release_id")

    p_evals = sub.add_parser("evals", help="List eval runs")
    p_evals.add_argument("--release-id", default=None)
    p_evals.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()
    global DEFAULT_BASE
    DEFAULT_BASE = args.base

    if args.cmd == "list":
        list_releases(args.status, args.limit)
    elif args.cmd == "show":
        show_release(args.release_id)
    elif args.cmd == "evals":
        list_evals(args.release_id, args.limit)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
