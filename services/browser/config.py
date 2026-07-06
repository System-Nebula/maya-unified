"""Browser capture service configuration."""

from __future__ import annotations

import os
from pathlib import Path

from services.paths import DATA_DIR

S3_ENDPOINT = os.environ.get("S3_ENDPOINT", os.environ.get("SEAWEEDFS_URL", "http://localhost:8333")).rstrip("/")
S3_BUCKET = os.environ.get("S3_BUCKET", "browser")
VALKEY_URL = os.environ.get("VALKEY_URL", "redis://localhost:6379")
VALKEY_STREAM = os.environ.get("BROWSER_CAPTURE_STREAM", "browser.capture")
VALKEY_MAXLEN = int(os.environ.get("BROWSER_CAPTURE_STREAM_MAXLEN", "100000"))
MAYA_BROWSER_CAPTURE_TOKEN = os.environ.get("MAYA_BROWSER_CAPTURE_TOKEN", "")
MAYA_CAPTURE_MDX_ROOT = Path(
    os.environ.get("MAYA_CAPTURE_MDX_ROOT", str(DATA_DIR / "captures"))
)
ENRICHd_URL = os.environ.get("ENRICHd_URL", "").rstrip("/")
PIPELINE_VERSION = "browser-capture-v1"

ASSET_EXTENSIONS: dict[str, str] = {
    "html": "html",
    "reader_html": "html",
    "screenshot": "webp",
    "dom_json": "json",
    "pdf": "pdf",
    "audio": "audio",
    "video": "video",
    "mhtml": "mhtml",
    "favicon": "ico",
}
