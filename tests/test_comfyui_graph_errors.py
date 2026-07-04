"""Tests for comfyui graph error summarization."""

from __future__ import annotations

import json
from types import SimpleNamespace

from maya_image.providers.comfyui_graph import _submit_timeout_sec, _summarize_comfy_error


def test_summarize_comfy_error_html_body() -> None:
    body = '<!DOCTYPE html><html lang="en"><head><link href="/_next/static/css/app.css" />'
    summary = _summarize_comfy_error(body, workflow_name="z-image-turbo-t2i", status_code=404)
    assert "COMFYUI_API_URL" in summary
    assert "HTML 404" in summary
    assert "<!DOCTYPE" not in summary
    assert len(summary) <= 201


def test_summarize_comfy_error_json_message() -> None:
    body = '{"message": "missing checkpoint"}'
    summary = _summarize_comfy_error(body, workflow_name="z-image-turbo-t2i")
    assert "missing checkpoint" in summary


def test_summarize_comfy_unreachable() -> None:
    from maya_image.providers.comfyui_graph import _summarize_comfy_unreachable

    summary = _summarize_comfy_unreachable(workflow_name="z-image-turbo-t2i", cause=ConnectionError("refused"))
    assert "COMFYUI_API_URL" in summary
    assert "comfyui-api running" in summary


def test_summarize_comfy_error_model_mount_mismatch() -> None:
    body = json.dumps(
        {
            "node_errors": {
                "29": {
                    "class_type": "VAELoader",
                    "errors": [
                        {
                            "type": "value_not_in_list",
                            "details": "vae_name: 'ae.safetensors' not in ['pixel_space']",
                            "extra_info": {"received_value": "ae.safetensors"},
                        }
                    ],
                },
                "28": {
                    "class_type": "UNETLoader",
                    "errors": [
                        {
                            "type": "value_not_in_list",
                            "details": "unet_name: 'z_image_turbo_bf16.safetensors' not in []",
                        }
                    ],
                },
            }
        }
    )
    summary = _summarize_comfy_error(body, workflow_name="z-image-turbo-t2i")
    assert "/opt/ComfyUI" in summary
    assert "infra/comfyui/README.md" in summary


def test_zimage_submit_timeout_defaults_to_180s() -> None:
    workflow = SimpleNamespace(
        id="z-image-turbo-t2i",
        name="z-image-turbo-t2i",
        params={"model_key": "z-image-turbo"},
    )
    assert _submit_timeout_sec(workflow) == 180.0


def test_non_zimage_submit_timeout_defaults_to_90s() -> None:
    workflow = SimpleNamespace(
        id="sd15-txt2img",
        name="sd15-txt2img",
        params={"model_key": "sd15"},
    )
    assert _submit_timeout_sec(workflow) == 90.0
