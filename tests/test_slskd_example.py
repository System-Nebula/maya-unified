"""Bundled example slskd stand-in + OpenBao first-run seed."""

from __future__ import annotations

import json
import threading
from http.server import ThreadingHTTPServer
from unittest.mock import patch
from urllib.request import Request, urlopen

from services.paths import ROOT
from services.secrets.openbao import (
    DEV_SEED_EXAMPLE,
    EXAMPLE_SLSKD_USERNAME,
    SLSKD_SECRET_PATH,
    ensure_local_dev_seed,
    init_dev,
    is_example_slskd_account,
    load_dev_seed,
)
from services.slskd_example.server import ExampleSlskdHandler, load_fixtures, responses_for

FIXTURES = ROOT / "examples" / "slskd" / "search_responses.json"


def test_bundled_seed_is_example_test_account(monkeypatch) -> None:
    monkeypatch.delenv("SLSKD_EXAMPLE", raising=False)
    monkeypatch.delenv("SLSKD_SLSK_USERNAME", raising=False)
    secrets = load_dev_seed(DEV_SEED_EXAMPLE)
    slskd = secrets[SLSKD_SECRET_PATH]
    assert slskd["username"] == EXAMPLE_SLSKD_USERNAME
    assert slskd["network"] == "example"
    assert is_example_slskd_account(slskd)
    assert not is_example_slskd_account({"username": "real-user", "network": ""})


def test_ensure_local_dev_seed_copies_once(tmp_path, monkeypatch) -> None:
    dest = tmp_path / "openbao" / "dev-seed.json"
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", dest)
    first = ensure_local_dev_seed()
    assert first == dest
    original = dest.read_text(encoding="utf-8")
    dest.write_text(original.replace(EXAMPLE_SLSKD_USERNAME, "custom-user"), encoding="utf-8")
    ensure_local_dev_seed()
    assert "custom-user" in dest.read_text(encoding="utf-8")


def test_init_dev_writes_example_when_kv_empty(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    monkeypatch.delenv("SLSKD_SLSK_USERNAME", raising=False)
    monkeypatch.delenv("SLSKD_SLSK_PASSWORD", raising=False)
    monkeypatch.setattr("services.secrets.openbao.DEV_SEED_LOCAL", tmp_path / "dev-seed.json")
    written: list[tuple[str, dict]] = []

    def fake_write(path: str, data: dict) -> None:
        written.append((path, data))

    with patch("services.secrets.openbao.bao_is_local", return_value=True):
        with patch(
            "services.secrets.openbao.slskd_credentials",
            return_value={"username": "", "password": "", "api_key": "", "network": ""},
        ):
            with patch("services.secrets.openbao.write_secret", side_effect=fake_write):
                status = init_dev()
    assert "example test account" in status
    assert written
    assert written[0][0] == SLSKD_SECRET_PATH
    assert written[0][1]["username"] == EXAMPLE_SLSKD_USERNAME


def test_init_dev_skips_remote(monkeypatch) -> None:
    monkeypatch.setenv("BAO_TOKEN", "dev-token")
    with patch("services.secrets.openbao.bao_is_local", return_value=False):
        with patch(
            "services.secrets.openbao.seed_slskd_from_env",
            return_value="openbao slskd secret missing; bao kv put",
        ) as seed:
            with patch("services.secrets.openbao.write_secret") as write:
                status = init_dev()
    seed.assert_called_once()
    write.assert_not_called()
    assert "missing" in status


def test_brat_fixture_keeps_flac_drops_lossy() -> None:
    responses = responses_for("brat", json.loads(FIXTURES.read_text(encoding="utf-8")))
    files = responses[0]["files"]
    names = [item["filename"] for item in files]
    assert any(name.endswith(".flac") for name in names)
    assert any(name.endswith(".mp3") for name in names)


def test_example_http_search_and_download() -> None:
    ExampleSlskdHandler.api_key = "ci-cloud-agent-slskd-key"
    ExampleSlskdHandler.fixtures = load_fixtures()
    ExampleSlskdHandler.searches = {}
    ExampleSlskdHandler.downloads = []
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), ExampleSlskdHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    headers = {"X-API-Key": "ci-cloud-agent-slskd-key", "Content-Type": "application/json"}
    try:
        app = json.loads(
            urlopen(
                Request(f"http://127.0.0.1:{port}/api/v0/application", headers=headers),
                timeout=2,
            ).read()
        )
        assert app["server"]["isLoggedIn"] is True
        created = json.loads(
            urlopen(
                Request(
                    f"http://127.0.0.1:{port}/api/v0/searches",
                    data=json.dumps({"searchText": "brat"}).encode(),
                    headers=headers,
                    method="POST",
                ),
                timeout=2,
            ).read()
        )
        search_id = created["id"]
        state = json.loads(
            urlopen(
                Request(
                    f"http://127.0.0.1:{port}/api/v0/searches/{search_id}?includeResponses=true",
                    headers=headers,
                ),
                timeout=2,
            ).read()
        )
        files = state["responses"][0]["files"]
        assert any(item["filename"].endswith(".flac") for item in files)
    finally:
        httpd.shutdown()
        httpd.server_close()
