#!/usr/bin/env python3
"""Download Krea 2 Turbo int8 convrot weights for local ComfyUI inference.

Pulls the Turbo daily-driver stack from Comfy-Org/Krea-2 and the official
ComfyUI workflow template. RAW bf16 is optional (--include-raw); legacy fp8
UNet is optional (--include-fp8).

Usage:
    uv run python infra/comfyui/scripts/fetch_krea2_weights.py --dry-run
    uv run python infra/comfyui/scripts/fetch_krea2_weights.py
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path

from _secrets import resolve_hf_token, token_source

_TEMPLATE_URL = os.getenv(
    "COMFYUI_KREA2_TEMPLATE_URL",
    "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_krea2_turbo_t2i.json",
)


@dataclass(frozen=True)
class Artifact:
    repo_id: str
    filename: str
    subdir: str
    approx_gb: float


TURBO_ARTIFACTS: tuple[Artifact, ...] = (
    Artifact("Comfy-Org/Krea-2", "krea2_turbo_int8_convrot.safetensors", "diffusion_models", 12.6),
    Artifact("Comfy-Org/Krea-2", "qwen3vl_4b_fp8_scaled.safetensors", "text_encoders", 2.5),
    Artifact("Comfy-Org/Krea-2", "qwen_image_vae.safetensors", "vae", 0.2),
)

FP8_ARTIFACTS: tuple[Artifact, ...] = (
    Artifact("Comfy-Org/Krea-2", "krea2_turbo_fp8_scaled.safetensors", "diffusion_models", 12.0),
)

RAW_ARTIFACTS: tuple[Artifact, ...] = (
    Artifact("Comfy-Org/Krea-2", "krea2_raw_bf16.safetensors", "diffusion_models", 24.0),
)


def _default_models_dir() -> Path:
    return Path(os.getenv("COMFYUI_MODELS_DIR", "~/ComfyUI/models")).expanduser()


def _default_workflow_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "workflows" / "krea2"


def _download_template(workflow_dir: Path, *, dry_run: bool) -> None:
    dest = workflow_dir / "image_krea2_turbo.json"
    if dry_run:
        print(f"  [dry-run] template -> {dest}")
        return
    import httpx

    try:
        resp = httpx.get(_TEMPLATE_URL, timeout=60.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  WARN: template download failed ({exc})")
        return
    workflow_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    print(f"  template -> {dest}")


def _fetch_artifacts(artifacts: tuple[Artifact, ...], models_dir: Path, token: str | None, *, dry_run: bool) -> tuple[list[dict], int]:
    recorded: list[dict] = []
    failures = 0
    for art in artifacts:
        target = models_dir / art.subdir / art.filename
        if dry_run:
            print(f"  [dry-run] {art.repo_id}:{art.filename} -> {target}  (~{art.approx_gb} GB)")
            continue
        from huggingface_hub import hf_hub_download

        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            path = hf_hub_download(
                repo_id=art.repo_id,
                filename=f"{art.subdir}/{art.filename}",
                local_dir=str(models_dir),
                token=token,
            )
        except Exception as exc:
            print(f"  FAIL {art.filename} -> {exc}")
            failures += 1
            continue
        size = Path(path).stat().st_size
        print(f"  OK {art.filename}  {size / 1024**3:.2f} GB")
        recorded.append({"file": str(target), "bytes": size})
    return recorded, failures


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Krea 2 weights for ComfyUI.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--include-raw", action="store_true", help="also fetch krea2_raw_bf16 (~24 GB)")
    parser.add_argument("--include-fp8", action="store_true", help="also fetch legacy krea2_turbo_fp8_scaled UNet (~12 GB)")
    parser.add_argument("--models-dir", type=Path, default=None)
    parser.add_argument("--workflow-dir", type=Path, default=None)
    parser.add_argument("--skip-workflow", action="store_true")
    args = parser.parse_args()

    models_dir = (args.models_dir or _default_models_dir()).expanduser()
    workflow_dir = args.workflow_dir or _default_workflow_dir()
    token = resolve_hf_token()

    artifacts = TURBO_ARTIFACTS
    if args.include_fp8:
        artifacts = artifacts + FP8_ARTIFACTS
    if args.include_raw:
        artifacts = artifacts + RAW_ARTIFACTS
    total_gb = sum(a.approx_gb for a in artifacts)

    print("Krea 2 provisioning")
    print(f"  models dir : {models_dir}")
    print(f"  hf token   : {'present' if token else 'MISSING'} (source: {token_source()})")
    print(f"  artifacts  : {len(artifacts)} files, ~{total_gb:.1f} GB\n")

    recorded, failures = _fetch_artifacts(artifacts, models_dir, token, dry_run=args.dry_run)

    if not args.skip_workflow:
        _download_template(workflow_dir, dry_run=args.dry_run)

    if not args.dry_run and recorded:
        manifest = models_dir / ".krea2.manifest.json"
        manifest.write_text(json.dumps(recorded, indent=2))
        print(f"\nwrote {manifest}")

    if failures:
        print(f"\n{failures} download(s) failed.")
        return 1
    print("\ndone." if not args.dry_run else "\ndry-run complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
