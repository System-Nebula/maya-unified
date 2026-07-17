"""SEC-007: Mailgun webhook fail-closed + HTML sanitization."""

from __future__ import annotations

import hashlib
import hmac
import time

import pytest
from fastapi import HTTPException
from services.auth.api_auth_registry import ApiAuthClass, classify_route

from maya_gateway.services.email_sanitize import ARTIFACT_CSP, sanitize_email_html
from maya_gateway.services.mailgun_webhook import (
    reset_replay_cache_for_tests,
    verify_mailgun_signature,
)


@pytest.fixture(autouse=True)
def _reset_replay():
    reset_replay_cache_for_tests()
    yield
    reset_replay_cache_for_tests()


def _sign(secret: str, timestamp: str, token: str) -> str:
    return hmac.new(
        secret.encode(),
        f"{timestamp}{token}".encode(),
        hashlib.sha256,
    ).hexdigest()


def test_missing_secret_fails_closed() -> None:
    with pytest.raises(HTTPException) as exc:
        verify_mailgun_signature("t", str(int(time.time())), "sig", secret="")
    assert exc.value.status_code == 503


def test_invalid_signature_fails() -> None:
    now = str(int(time.time()))
    with pytest.raises(HTTPException) as exc:
        verify_mailgun_signature("tok", now, "deadbeef", secret="mailbox-secret")
    assert exc.value.status_code == 401


def test_stale_timestamp_fails() -> None:
    secret = "mailbox-secret"
    ts = str(int(time.time()) - 3600)
    token = "tok-1"
    sig = _sign(secret, ts, token)
    with pytest.raises(HTTPException) as exc:
        verify_mailgun_signature(token, ts, sig, secret=secret)
    assert exc.value.status_code == 401
    assert "stale" in str(exc.value.detail).lower()


def test_replayed_token_fails() -> None:
    secret = "mailbox-secret"
    ts = str(int(time.time()))
    token = "tok-replay"
    sig = _sign(secret, ts, token)
    verify_mailgun_signature(token, ts, sig, secret=secret)
    with pytest.raises(HTTPException) as exc:
        verify_mailgun_signature(token, ts, sig, secret=secret)
    assert exc.value.status_code == 401
    assert "replay" in str(exc.value.detail).lower()


def test_sanitize_strips_dangerous_markup() -> None:
    dirty = """
    <html><body>
      <p onclick="alert(1)">Hello <script>alert(2)</script></p>
      <a href="javascript:alert(3)">x</a>
      <iframe src="https://evil"></iframe>
      <form action="/api/auth/login"><input name="password"></form>
      <img src="https://cdn.example/x.png" onerror="alert(4)">
    </body></html>
    """
    clean = sanitize_email_html(dirty)
    assert "<script" not in clean.lower()
    assert "onclick" not in clean.lower()
    assert "javascript:" not in clean.lower()
    assert "<iframe" not in clean.lower()
    assert "<form" not in clean.lower()
    assert "<input" not in clean.lower()
    assert "onerror" not in clean.lower()
    assert "https://cdn.example/x.png" in clean
    assert "Hello" in clean


def test_artifact_csp_is_sandboxed_without_scripts() -> None:
    assert "sandbox" in ARTIFACT_CSP
    assert "allow-scripts" not in ARTIFACT_CSP
    assert "allow-same-origin" not in ARTIFACT_CSP


def test_mailgun_webhook_is_service_authenticated_in_unified_gateway() -> None:
    auth_class = classify_route("POST", "/api/discover/inbox/webhook")
    assert auth_class is ApiAuthClass.SERVICE
