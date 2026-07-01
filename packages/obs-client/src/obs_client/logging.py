"""Structlog configuration with optional OTEL trace correlation."""

from __future__ import annotations

import logging
import os

import structlog


def configure_logging(service_name: str, log_level: str = "INFO") -> None:
    """Configure structlog with JSON output and OTEL trace/span ID injection."""
    log_level_int = getattr(logging, log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    root = logging.getLogger()
    root.setLevel(log_level_int)

    if not root.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(log_level_int)
        root.addHandler(handler)

    # Optional OTLP handler if endpoint is configured
    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
    if endpoint:
        try:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.sdk.resources import Resource

            provider = LoggerProvider(
                resource=Resource.create(
                    {
                        "service.name": service_name,
                        "deployment.environment": os.environ.get("ENV", "development"),
                    }
                )
            )
            provider.add_log_record_processor(
                BatchLogRecordProcessor(OTLPLogExporter(endpoint=endpoint))
            )
            set_logger_provider(provider)
            root.addHandler(LoggingHandler(level=log_level_int, logger_provider=provider))
        except ImportError:
            pass
