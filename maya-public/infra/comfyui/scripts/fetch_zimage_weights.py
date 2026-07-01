#!/usr/bin/env python3
"""Token-aware downloader for Z-Image-Turbo ComfyUI workflow weights.

Z-Image-Turbo (Tongyi-MAI/Alibaba) is a 6B S3-DiT distilled model (8 NFE, CFG=0)
that fits in 16 GB VRAM. This script downloads the BF16 diffusion model, Qwen-3-4B
text encoder, and the shared Flux VAE from Comfy-Org/z_image_turbo.

Usage:
    uv run python infra/comfyui/scripts/fetch_zimage_weights.py --dry-run
    uv run python infra/comfyui/scripts/fetch_zimage_weights.py            # ~15 GB
    COMFYUI_MODELS_DIR=~/ComfyUI/models uv run python .../fetch_zimage_weights.py
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from _secrets import resolve_hf_token, token_source


@dataclass(frozen=True)
class Artifact:
    repo_id: str
    hf_path: str
    subdir: str
    filename: str
    approx_gb: float


# Source: https://huggingface.co/Comfy-Org/z_image_turbo
# Apache-2.0 license — no token required for download, but token may help with rate limits.
ARTIFACTS: tuple[Artifact, ...] = (
    Artifact("Comfy-Org/z_image_turbo",
             "split_files/diffusion_models/z_image_turbo_bf16.safetensors",
             "diffusion_models", "z_image_turbo_bf16.safetensors", 12.0),
    Artifact("Comfy-Org/z_image_turbo",
             "split_files/text_encoders/qwen_3_4b.safetensors",
             "text_encoders", "qwen_3_4b.safetensors", 2.2),
    Artifact("Comfy-Org/z_image_turbo",
             "split_files/vae/ae.safetensors",
             "vae", "ae.safetensors", 0.34),
)

_TEMPLATE_URL = os.getenv(
    "COMFYUI_ZIMAGE_TEMPLATE_URL",
    "https://raw.githubusercontent.com/Comfy-Org/workflow_templates/main/templates/image_z_image_turbo.json",
)
_SIZE_TOLERANCE = 0.35


def _default_models_dir() -> Path:
    return Path(os.getenv("COMFYUI_MODELS_DIR", "~/ComfyUI/models")).expanduser()


def _default_workflow_dir() -> Path:
    return Path(__file__).resolve().parent.parent / "workflows" / "zimage"


def _size_ok(actual_bytes: int, approx_gb: float) -> bool:
    expected = approx_gb * 1024**3
    return abs(actual_bytes - expected) <= expected * _SIZE_TOLERANCE


def _download_template(workflow_dir: Path, *, dry_run: bool) -> dict | None:
    dest = workflow_dir / "image_z_image_turbo.json"
    if dry_run:
        print(f"  [dry-run] template -> {dest}  (from {_TEMPLATE_URL})")
        return None
    import httpx
    try:
        resp = httpx.get(_TEMPLATE_URL, timeout=30.0, follow_redirects=True)
        resp.raise_for_status()
    except Exception as exc:
        print(f"  WARN: template download failed ({exc}); grab from Comfy Template Library into {dest}")
        return None
    workflow_dir.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(resp.content)
    print(f"  template -> {dest}")
    return {"path": str(dest), "bytes": len(resp.content)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download Z-Image-Turbo weights for ComfyUI.")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--models-dir", type=Path, default=None)
    parser.add_argument("--workflow-dir", type=Path, default=None)
    parser.add_argument("--skip-workflow", action="store_true")
    args = parser.parse_args()

    models_dir = (args.models_dir or _default_models_dir()).expanduser()
    workflow_dir = args.workflow_dir or _default_workflow_dir()
    token = resolve_hf_token()

    print("Z-Image-Turbo provisioning")
    print(f"  models dir : {models_dir}")
    print(f"  hf token   : {'present' if token else 'not set (ok, Apache-2.0)'} (source: {token_source()})")
    total_gb = sum(a.approx_gb for a in ARTIFACTS)
    print(f"  artifacts  : {len(ARTIFACTS)} files, ~{total_gb:.1f} GB\n")

    recorded: list[dict] = []
    failures = 0

    for art in ARTIFACTS:
        target = models_dir / art.subdir / art.filename
        if args.dry_run:
            print(f"  [dry-run] {art.repo_id}:{art.hf_path} -> {target}  (~{art.approx_gb} GB)")
            continue
        from huggingface_hub import hf_hub_download

        target.parent.mkdir(parents=True, exist_ok=True)
        cache_dir = models_dir / ".hf_cache"
        try:
            tmp_path = hf_hub_download(
                repo_id=art.repo_id,
                filename=art.hf_path,
                cache_dir=str(cache_dir),
                token=token,
            )
            shutil.copy2(tmp_path, target)
        except Exception as exc:
            print(f"  FAIL {art.repo_id}:{art.hf_path} -> {exc}")
            failures += 1
            continue
        size = target.stat().st_size
        ok = _size_ok(size, art.approx_gb)
        print(f"  {'OK ' if ok else 'WARN'} {art.filename}  {size / 1024**3:.2f} GB"
              f"{'' if ok else ' (size outside expected band)'}")
        recorded.append({"file": str(target), "bytes": size, "size_ok": ok})

    if not args.skip_workflow:
        tpl = _download_template(workflow_dir, dry_run=args.dry_run)
        if tpl:
            recorded.append(tpl)

    if not args.dry_run and recorded:
        manifest = models_dir / ".zimage.manifest.json"
        manifest.write_text(json.dumps(recorded, indent=2))
        print(f"\nwrote {manifest}")

    if failures:
        print(f"\n{failures} download(s) failed.")
        return 1
    print("\ndone." if not args.dry_run else "\ndry-run complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
