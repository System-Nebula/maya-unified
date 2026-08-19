"""Optional OpenTelemetry hooks for catalog mapping.

No-op when the OTEL SDK is not configured (ProxyTracer / non-recording spans).
"""

from __future__ import annotations

from opentelemetry import trace

TRACER = trace.get_tracer("maya.music.catalog")


def record_http(status: int | None, *, error: str | None = None, hits: int | None = None) -> None:
    span = trace.get_current_span()
    if not span.is_recording():
        return
    if status is not None:
        span.set_attribute("http.status_code", int(status))
    if hits is not None:
        span.set_attribute("catalog.hit_count", int(hits))
    if error:
        span.set_attribute("catalog.error", error[:160])
