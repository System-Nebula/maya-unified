"""PKCE helper tests."""

from __future__ import annotations

import base64
import hashlib

from services.integrations.google.oauth import _generate_pkce_pair


def test_generate_pkce_pair_challenge_matches_verifier():
    verifier, challenge = _generate_pkce_pair()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    expected = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    assert challenge == expected
    assert len(verifier) >= 32
