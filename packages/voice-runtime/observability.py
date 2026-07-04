"""Structured logging and OpenTelemetry (traces, logs, metrics).

Enable with VA_OTEL_ENABLED=1. Export to a collector via standard OTLP env vars
or use VA_OTEL_EXPORTER=console for local debugging.

Typical collector setup (Grafana Alloy, Jaeger, Datadog agent, etc.):

    OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
    VA_OTEL_ENABLED=1
    VA_LOG_FORMAT=json
"""

from __future__ import annotations

import json
import logging
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

_configured = False
_tracer: Any = None
_meter: Any = None
_turn_counter: Any = None
_tool_counter: Any = None
_error_counter: Any = None
_llm_probe_latency: Any = None
_llm_probe_counter: Any = None
_tts_ttfa_latency: Any = None
_tts_synth_latency: Any = None
_tts_encode_latency: Any = None


class _JsonFormatter(logging.Formatter):
    """One JSON object per log line for Loki / Elasticsearch / OTLP pipelines."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        # OpenTelemetry logging instrumentation adds trace_id / span_id on the record.
        trace_id = getattr(record, "otelTraceID", None) or getattr(record, "trace_id", None)
        span_id = getattr(record, "otelSpanID", None) or getattr(record, "span_id", None)
        if trace_id and trace_id != "0":
            payload["trace_id"] = trace_id
        if span_id and span_id != "0":
            payload["span_id"] = span_id
        for key, val in record.__dict__.items():
            if key.startswith("_") or key in {
                "name", "msg", "args", "created", "filename", "funcName", "levelname",
                "levelno", "lineno", "module", "msecs", "message", "pathname",
                "process", "processName", "relativeCreated", "stack_info", "thread",
                "threadName", "exc_info", "exc_text", "otelTraceID", "otelSpanID",
                "otelTraceSampled", "otelServiceName",
            }:
                continue
            if isinstance(val, (str, int, float, bool)) or val is None:
                payload[key] = val
        return json.dumps(payload, ensure_ascii=False, default=str)


def setup_observability() -> None:
    """Configure stdlib logging and optional OpenTelemetry exporters."""
    global _configured, _tracer, _meter, _turn_counter, _tool_counter, _error_counter
    global _llm_probe_latency, _llm_probe_counter
    global _tts_ttfa_latency, _tts_synth_latency, _tts_encode_latency
    if _configured:
        return

    from config import CONFIG

    obs = CONFIG.observability
    level = getattr(logging, obs.log_level.upper(), logging.INFO)

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stderr)
    if obs.log_format.lower() == "json":
        handler.setFormatter(_JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter(
                "%(asctime)s %(levelname)-5s [%(name)s] %(message)s",
                datefmt="%H:%M:%S",
            )
        )
    root.addHandler(handler)

    # Quieter third-party noise unless debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("discord").setLevel(logging.INFO)
    logging.getLogger("discord.http").setLevel(logging.WARNING)

    if obs.enabled:
        _setup_otel(obs, root)

    _configured = True
    log = get_logger("observability")
    log.info(
        "logging ready level=%s format=%s otel=%s exporter=%s",
        obs.log_level,
        obs.log_format,
        obs.enabled,
        obs.exporter if obs.enabled else "off",
    )
    if obs.enabled and obs.exporter.lower() == "otlp":
        log.info(
            "OTEL export -> %s (Jaeger UI usually http://localhost:16686)",
            obs.otlp_endpoint,
        )


def _setup_otel(obs, root: logging.Logger) -> None:
    global _tracer, _meter, _turn_counter, _tool_counter, _error_counter
    global _llm_probe_latency, _llm_probe_counter
    global _tts_ttfa_latency, _tts_synth_latency, _tts_encode_latency
    try:
        from opentelemetry import metrics, trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
    except ImportError:
        root.warning(
            "VA_OTEL_ENABLED but OpenTelemetry SDK is not installed — "
            "pip install opentelemetry-sdk opentelemetry-exporter-otlp-proto-grpc"
        )
        return

    resource = Resource.create({
        "service.name": obs.service_name,
        "service.version": obs.service_version,
    })

    if obs.traces_enabled:
        provider = TracerProvider(resource=resource)
        provider.add_span_processor(BatchSpanProcessor(_span_exporter(obs)))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer(obs.service_name, obs.service_version)

    if obs.metrics_enabled:
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader

            readers = []
            if obs.exporter.lower() == "console":
                readers.append(PeriodicExportingMetricReader(ConsoleMetricExporter()))
            else:
                readers.append(PeriodicExportingMetricReader(_metric_exporter(obs)))
            meter_provider = MeterProvider(resource=resource, metric_readers=readers)
            metrics.set_meter_provider(meter_provider)
            _meter = metrics.get_meter(obs.service_name, obs.service_version)
            _turn_counter = _meter.create_counter("voice.turns", description="Completed user turns")
            _tool_counter = _meter.create_counter("voice.tool.calls", description="Tool invocations")
            _error_counter = _meter.create_counter("voice.errors", description="Handled errors")
            _llm_probe_latency = _meter.create_histogram(
                "llm.health.latency",
                unit="ms",
                description="LLM health-probe latency",
            )
            _llm_probe_counter = _meter.create_counter(
                "llm.health.checks",
                description="LLM health probes",
            )
            _tts_ttfa_latency = _meter.create_histogram(
                "tts.ttfa",
                unit="ms",
                description="TTS time-to-first-audio",
            )
            _tts_synth_latency = _meter.create_histogram(
                "tts.synth",
                unit="ms",
                description="TTS synthesis wall time",
            )
            _tts_encode_latency = _meter.create_histogram(
                "tts.encode",
                unit="ms",
                description="TTS WAV encode time",
            )
        except Exception as exc:  # noqa: BLE001
            root.warning("OTEL metrics disabled: %s", exc)

    if obs.logs_enabled and obs.exporter.lower() == "otlp":
        _setup_otel_logs(obs, resource, root)

    try:
        from opentelemetry.instrumentation.logging import LoggingInstrumentor

        LoggingInstrumentor().instrument(set_logging_format=False)
    except ImportError:
        root.debug("opentelemetry-instrumentation-logging not installed; trace/log correlation skipped")
    except Exception as exc:  # noqa: BLE001
        root.debug("logging instrumentation skipped: %s", exc)


def _span_exporter(obs):
    if obs.exporter.lower() == "console":
        from opentelemetry.sdk.trace.export import ConsoleSpanExporter

        return ConsoleSpanExporter()
    if obs.otlp_protocol.lower() in {"http", "http/protobuf"}:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return OTLPSpanExporter(endpoint=obs.otlp_traces_endpoint or obs.otlp_endpoint)
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    return OTLPSpanExporter(endpoint=obs.otlp_endpoint, insecure=obs.otlp_insecure)


def _metric_exporter(obs):
    if obs.otlp_protocol.lower() in {"http", "http/protobuf"}:
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter

        return OTLPMetricExporter(endpoint=obs.otlp_metrics_endpoint or obs.otlp_endpoint)
    from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter

    return OTLPMetricExporter(endpoint=obs.otlp_endpoint, insecure=obs.otlp_insecure)


def _setup_otel_logs(obs, resource, root: logging.Logger) -> None:
    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor, ConsoleLogExporter
    except ImportError:
        root.debug("OTEL log export unavailable in this SDK version")
        return

    provider = LoggerProvider(resource=resource)
    if obs.exporter.lower() == "console":
        provider.add_log_record_processor(BatchLogRecordProcessor(ConsoleLogExporter()))
    else:
        if obs.otlp_protocol.lower() in {"http", "http/protobuf"}:
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter

            exporter = OTLPLogExporter(endpoint=obs.otlp_logs_endpoint or obs.otlp_endpoint)
        else:
            from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter

            exporter = OTLPLogExporter(endpoint=obs.otlp_endpoint, insecure=obs.otlp_insecure)
        provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    set_logger_provider(provider)
    root.addHandler(LoggingHandler(level=logging.NOTSET, logger_provider=provider))


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def get_tracer(name: str = "voice-agent"):
    global _tracer
    if _tracer is not None:
        return _tracer
    try:
        from opentelemetry import trace

        return trace.get_tracer(name)
    except ImportError:
        return _NoOpTracer()


class _NoOpTracer:
    @contextmanager
    def start_as_current_span(self, name: str, **kwargs) -> Iterator[Any]:
        yield _NoOpSpan()


class _NoOpSpan:
    def set_attribute(self, key: str, value: Any) -> None:
        pass

    def add_event(self, name: str, attributes: dict[str, Any] | None = None) -> None:
        pass

    def record_exception(self, exc: BaseException) -> None:
        pass


@contextmanager
def span(name: str, **attributes: Any) -> Iterator[Any]:
    """Start a trace span when OTEL is enabled; no-op otherwise."""
    tr = get_tracer("voice-agent")
    with tr.start_as_current_span(name) as sp:
        for key, val in attributes.items():
            if val is not None:
                try:
                    sp.set_attribute(key, val)
                except Exception:  # noqa: BLE001
                    pass
        yield sp


def record_turn() -> None:
    if _turn_counter is not None:
        _turn_counter.add(1)


def record_tool(tool: str, *, error: bool = False) -> None:
    if _tool_counter is not None:
        _tool_counter.add(1, {"tool.name": tool, "error": error})
    if error and _error_counter is not None:
        _error_counter.add(1, {"component": "tool", "tool.name": tool})


def record_error(component: str, **attrs: Any) -> None:
    if _error_counter is not None:
        labels = {"component": component}
        labels.update({k: str(v) for k, v in attrs.items() if v is not None})
        _error_counter.add(1, labels)


def record_llm_probe(
    latency_ms: float,
    *,
    status: str,
    provider: str,
    model: str,
    phase: str,
    error_type: str | None = None,
) -> None:
    """Record LLM health-probe latency and outcome (metadata only, no payloads)."""
    attrs: dict[str, str | bool] = {
        "llm.provider": provider,
        "llm.model": model,
        "llm.health.status": status,
        "llm.health.phase": phase,
    }
    if error_type:
        attrs["error.type"] = error_type
    if _llm_probe_latency is not None:
        _llm_probe_latency.record(latency_ms, attrs)
    if _llm_probe_counter is not None:
        _llm_probe_counter.add(1, attrs)


def record_tts(timing: dict[str, float | int]) -> None:
    """Record TTS latency histograms (metadata only)."""
    if _tts_ttfa_latency is not None and timing.get("ttfa_ms") is not None:
        _tts_ttfa_latency.record(float(timing["ttfa_ms"]))
    if _tts_synth_latency is not None and timing.get("synth_ms") is not None:
        _tts_synth_latency.record(float(timing["synth_ms"]))
    if _tts_encode_latency is not None and timing.get("encode_ms") is not None:
        _tts_encode_latency.record(float(timing["encode_ms"]))
