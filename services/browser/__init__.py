"""Browser capture ingestion — extension events to object store + Postgres."""

from services.browser.capture import process_capture

__all__ = ["process_capture"]
