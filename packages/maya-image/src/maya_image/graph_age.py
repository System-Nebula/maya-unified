"""Optional Apache AGE graph — best-effort no-op in public build."""

from __future__ import annotations


class _AgeStub:
    def execute(self, *_args, **_kwargs):
        return None


def get_age():
    return _AgeStub()


def record_image_turn(*_args, **_kwargs) -> None:
    return None


def update_turn_rating(*_args, **_kwargs) -> None:
    return None
