"""Config tests for Google OAuth redirect URIs."""

from __future__ import annotations

import importlib
import os
from unittest.mock import MagicMock, patch


def _reload_config(**env: str):
    with patch.dict(os.environ, env, clear=False):
        import services.integrations.google.config as cfg

        return importlib.reload(cfg)


def _mock_request(*, host: str, scheme: str = "http"):
    request = MagicMock()
    request.url.scheme = scheme
    request.url.netloc = host
    request.headers.get.return_value = host
    return request


def test_login_redirect_uses_legacy_google_redirect_uri():
    cfg = _reload_config(
        GOOGLE_REDIRECT_URI="http://127.0.0.1:8090/auth/google/callback",
        GOOGLE_LOGIN_REDIRECT_URI="",
        MAYA_OAUTH_DYNAMIC_REDIRECT="0",
        MAYA_APP_BASE_URL="http://localhost:8090",
    )
    assert cfg.GOOGLE_LOGIN_REDIRECT_URI == "http://127.0.0.1:8090/auth/google/callback"


def test_app_base_url_prefers_maya_gateway_url():
    cfg = _reload_config(
        MAYA_APP_BASE_URL="",
        MAYA_GATEWAY_URL="http://127.0.0.1:8090",
        MAYA_PUBLIC_URL="http://localhost:8090",
    )
    assert cfg.APP_BASE_URL == "http://127.0.0.1:8090"


def test_redirect_uri_for_request_uses_browser_host_when_dynamic():
    env = {
        "MAYA_OAUTH_DYNAMIC_REDIRECT": "1",
        "GOOGLE_LOGIN_REDIRECT_URI": "http://localhost:8090/auth/google/callback",
    }
    with patch.dict(os.environ, env, clear=False):
        import services.integrations.google.config as cfg

        cfg = importlib.reload(cfg)
        request = _mock_request(host="127.0.0.1:8090")
        assert (
            cfg.redirect_uri_for_request(request, flow="login")
            == "http://127.0.0.1:8090/auth/google/callback"
        )


def test_redirect_uri_for_request_uses_static_when_dynamic_disabled():
    env = {
        "MAYA_OAUTH_DYNAMIC_REDIRECT": "0",
        "GOOGLE_LOGIN_REDIRECT_URI": "http://localhost:8090/auth/google/callback",
    }
    with patch.dict(os.environ, env, clear=False):
        import services.integrations.google.config as cfg

        cfg = importlib.reload(cfg)
        request = _mock_request(host="127.0.0.1:8090")
        assert (
            cfg.redirect_uri_for_request(request, flow="login")
            == "http://localhost:8090/auth/google/callback"
        )


def test_google_console_checklist_includes_localhost_and_loopback():
    cfg = _reload_config(MAYA_APP_BASE_URL="http://localhost:8090")
    checklist = cfg.google_console_checklist(port=8090)
    assert "http://localhost:8090/auth/google/callback" in checklist["redirect_uris"]
    assert "http://127.0.0.1:8090/auth/google/callback" in checklist["redirect_uris"]
    assert "http://localhost:8090" in checklist["javascript_origins"]
    assert "http://127.0.0.1:8090" in checklist["javascript_origins"]
