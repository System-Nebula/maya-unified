"""Bundled slskd HTTP stand-in for first-run reproduction (no Soulseek network)."""

from __future__ import annotations

import json
import os
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from services.paths import ROOT

FIXTURE_PATH = ROOT / "examples" / "slskd" / "search_responses.json"
DEFAULT_API_KEY = "ci-cloud-agent-slskd-key"


def load_fixtures() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def responses_for(search_text: str, fixtures: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    text = (search_text or "").lower()
    data = fixtures if fixtures is not None else load_fixtures()
    if "brat" in text or "charli" in text:
        key = "brat"
    elif "astley" in text or "never gonna" in text or '7"' in text or "7inch" in text:
        key = "nggyu"
    elif "brat" not in data and "nggyu" in data:
        key = "nggyu"
    else:
        key = "brat" if "brat" in data else next(iter(data), "")
    block = data.get(key) or {}
    responses = block.get("responses")
    return list(responses) if isinstance(responses, list) else []


class ExampleSlskdHandler(BaseHTTPRequestHandler):
    server_version = "maya-slskd-example/1"
    api_key = DEFAULT_API_KEY
    fixtures: dict[str, Any] = {}
    searches: dict[str, dict[str, Any]] = {}
    downloads: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []

    def log_message(self, format: str, *args: object) -> None:
        return

    def _authorized(self) -> bool:
        provided = self.headers.get("X-API-Key") or ""
        return bool(self.api_key) and provided == self.api_key

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_body(self) -> Any:
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return None
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return None

    def _read_json(self) -> dict[str, Any]:
        payload = self._read_body()
        return payload if isinstance(payload, dict) else {}

    def _deny(self) -> None:
        self._json({"message": "Unauthorized"}, status=401)

    def _user_download(self, username: str) -> dict[str, Any]:
        for row in self.downloads:
            if row.get("username") == username:
                return row
        row = {"username": username, "directories": []}
        self.downloads.append(row)
        return row

    def do_GET(self) -> None:  # noqa: N802
        if not self._authorized():
            self._deny()
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        query = parse_qs(parsed.query)
        if path == "/api/v0/application":
            self._json(
                {
                    "version": {"full": "example", "current": "example"},
                    "pendingReconnect": False,
                    "server": {
                        "state": "Connected",
                        "isConnected": True,
                        "isConnecting": False,
                        "isLoggedIn": True,
                        "isLoggingIn": False,
                        "isTransitioning": False,
                    },
                }
            )
            return
        if path.startswith("/api/v0/searches/"):
            search_id = unquote(path.rsplit("/", 1)[-1])
            record = self.searches.get(search_id)
            if record is None:
                self._json({"message": "not found"}, status=404)
                return
            include = str(query.get("includeResponses", ["false"])[0]).lower() in {
                "1",
                "true",
                "yes",
            }
            payload = dict(record)
            if not include:
                payload.pop("responses", None)
            self._json(payload)
            return
        if path in {"/api/v0/transfers/downloads", "/api/v0/transfers/downloads/"}:
            self._json(list(self.downloads))
            return
        if path in {"/api/v0/events", "/api/v0/events/"}:
            self._json(list(self.events))
            return
        self._json({"message": "not found"}, status=404)

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            self._deny()
            return
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if path == "/api/v0/searches":
            body = self._read_json()
            search_id = str(body.get("id") or uuid.uuid4())
            text = str(body.get("searchText") or "")
            record = {
                "id": search_id,
                "searchText": text,
                "isComplete": True,
                "responses": responses_for(text, self.fixtures),
            }
            self.searches[search_id] = record
            self._json({"id": search_id})
            return
        if path.startswith("/api/v0/transfers/downloads/"):
            username = unquote(path.rsplit("/", 1)[-1])
            body = self._read_body()
            files = body if isinstance(body, list) else []
            if isinstance(body, dict) and body:
                files = [body]
            user_row = self._user_download(username)
            directories: list[dict[str, Any]] = user_row.setdefault("directories", [])
            last_id = ""
            for item in files:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "")
                size = int(item.get("size") or 0)
                transfer_id = str(item.get("id") or f"xfer-{uuid.uuid4().hex[:8]}")
                last_id = transfer_id
                file_row = {
                    "id": transfer_id,
                    "username": username,
                    "direction": "Download",
                    "filename": filename,
                    "size": size,
                    "startOffset": int(item.get("startOffset") or 0),
                    "state": "Completed, Succeeded",
                    "bytesTransferred": size,
                    "percentComplete": 100.0,
                    "bytesRemaining": 0,
                    "averageSpeed": 0.0,
                    "requestedAt": "",
                }
                parent = str(filename.rsplit("\\", 1)[0] if "\\" in filename else "")
                directory = next((d for d in directories if d.get("directory") == parent), None)
                if directory is None:
                    directory = {"directory": parent, "fileCount": 0, "files": []}
                    directories.append(directory)
                directory["files"].append(file_row)
                directory["fileCount"] = len(directory["files"])
                self.events.append(
                    {
                        "id": str(uuid.uuid4()),
                        "timestamp": "",
                        "type": "DownloadFileComplete",
                        "data": json.dumps({"filename": filename, "size": size, "id": transfer_id}),
                    }
                )
            # slskd-api treats any 2xx as success (bool). Include an id for direct HTTP tests.
            self._json({"id": last_id or f"xfer-{uuid.uuid4().hex[:8]}"})
            return
        self._json({"message": "not found"}, status=404)


def serve(host: str = "127.0.0.1", port: int = 5030, api_key: str | None = None) -> None:
    ExampleSlskdHandler.api_key = api_key or os.environ.get("SLSKD_API_KEY") or DEFAULT_API_KEY
    ExampleSlskdHandler.fixtures = load_fixtures()
    ExampleSlskdHandler.searches = {}
    ExampleSlskdHandler.downloads = []
    ExampleSlskdHandler.events = []
    httpd = ThreadingHTTPServer((host, port), ExampleSlskdHandler)
    httpd.serve_forever()


if __name__ == "__main__":
    serve()
