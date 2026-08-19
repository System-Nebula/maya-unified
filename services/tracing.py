"""Shared OpenTelemetry helpers for play / music / player spans."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterator

from opentelemetry import baggage, trace

_PLAY_TRACER_NAME = "maya.play"


def corr_id_from_baggage() -> str | None:
    val = baggage.get_baggage("corr_id")
    return str(val) if val else None


@contextmanager
def corr_span(name: str, **attrs: Any) -> Iterator[trace.Span]:
    tracer = trace.get_tracer(_PLAY_TRACER_NAME)
    with tracer.start_as_current_span(name) as span:
        corr_id = corr_id_from_baggage()
        if corr_id:
            span.set_attribute("chat.corr_id", corr_id)
        for key, value in attrs.items():
            if value is not None:
                span.set_attribute(key, value)
        yield span


def _assign_tracer_provider(provider) -> None:
    """Swap the global tracer provider, including in tests that already set one."""
    import opentelemetry.trace as trace_api

    once = getattr(trace_api, "_TRACER_PROVIDER_SET_ONCE", None)
    if provider is None:
        trace_api._TRACER_PROVIDER = None  # noqa: SLF001
        if once is not None:
            once._done = False  # noqa: SLF001
        return
    trace_api._TRACER_PROVIDER = provider  # noqa: SLF001
    if once is not None:
        once._done = True  # noqa: SLF001


def restore_tracer_provider(previous) -> None:
    from opentelemetry.trace import ProxyTracerProvider

    if previous is None or isinstance(previous, ProxyTracerProvider):
        _assign_tracer_provider(None)
        return
    _assign_tracer_provider(previous)


def attach_in_memory_exporter(service_name: str):
    """Install an in-memory span exporter. Returns ``(exporter, previous_provider)``.

    Caller must restore ``previous_provider`` (and preferably ``provider.shutdown()``).
    Returns ``(None, None)`` when the OTEL SDK is not installed.
    """
    try:
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor
        from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
    except ImportError:
        return None, None
    exporter = InMemorySpanExporter()
    provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    previous = trace.get_tracer_provider()
    _assign_tracer_provider(provider)
    return exporter, previous


def span_records(exporter) -> list[dict[str, Any]]:
    if exporter is None:
        return []
    rows: list[dict[str, Any]] = []
    for span in exporter.get_finished_spans():
        ctx = span.get_span_context()
        parent = span.parent.span_id if span.parent else 0
        start = span.start_time or 0
        end = span.end_time or start
        rows.append(
            {
                "name": span.name,
                "trace_id": format(ctx.trace_id, "032x"),
                "span_id": format(ctx.span_id, "016x"),
                "parent_span_id": format(parent, "016x") if parent else None,
                "duration_ms": round((end - start) / 1_000_000, 2),
                "status": span.status.status_code.name if span.status else "UNSET",
                "attributes": {k: v for k, v in (span.attributes or {}).items()},
            }
        )
    rows.sort(key=lambda row: (row["trace_id"], row["name"]))
    return rows
