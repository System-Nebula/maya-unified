"""Shared OpenTelemetry helpers for play / music / player spans."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import baggage, trace

_tracer = trace.get_tracer("maya.play")


def corr_id_from_baggage() -> str | None:
    val = baggage.get_baggage("corr_id")
    return str(val) if val else None


@contextmanager
def corr_span(name: str, **attrs: Any) -> Iterator[trace.Span]:
    with _tracer.start_as_current_span(name) as span:
        corr_id = corr_id_from_baggage()
        if corr_id:
            span.set_attribute("chat.corr_id", corr_id)
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span
