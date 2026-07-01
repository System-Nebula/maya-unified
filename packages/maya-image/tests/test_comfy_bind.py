"""Unit tests for ComfyUI workflow binding."""

from __future__ import annotations

from maya_image.comfy_bind import auto_bind, build_values_from_request, inject, inject_request, is_arena_request, normalize_arena_resolution, set_path
from maya_image.comfy_graphs import create_anima_t2i_graph, create_z_image_turbo_graph
from maya_image.types.image_job import ImageJobInput, ImageMode


def test_set_path_updates_node_input():
    graph = {"5": {"inputs": {"width": 512, "height": 512}}}
    set_path(graph, "5.inputs.width", 1024)
    assert graph["5"]["inputs"]["width"] == 1024


def test_inject_prompt_and_dimensions():
    graph = create_z_image_turbo_graph(width=512, height=512, prompt="placeholder")
    bindings = auto_bind(graph)
    result = inject(
        graph,
        bindings,
        {
            "prompt": "neon alley at night",
            "width": 1152,
            "height": 2048,
            "steps": 8,
            "cfg": 1.2,
            "seed": 42,
        },
    )
    assert result["45"]["inputs"]["text"] == "neon alley at night"
    assert result["41"]["inputs"]["width"] == 1152
    assert result["41"]["inputs"]["height"] == 2048
    assert result["44"]["inputs"]["steps"] == 8
    assert result["44"]["inputs"]["cfg"] == 1.2
    assert result["44"]["inputs"]["seed"] == 42


def test_build_values_from_request_aspect():
    request = ImageJobInput(
        prompt="test",
        mode=ImageMode.GENERATE,
        size="1024x1024",
        metadata={"aspect": "16:9"},
    )
    values = build_values_from_request(request, params={"steps": 12, "cfg": 1.2})
    assert values["width"] == 1024
    assert values["height"] == 576
    assert values["steps"] == 12


def test_build_values_from_request_arena_ignores_workflow_aspect():
    request = ImageJobInput(
        prompt="test",
        mode=ImageMode.ARENA,
        size="1024x1024",
        metadata={"arena_slot": "a"},
    )
    values = build_values_from_request(
        request,
        params={"aspect": "9:16", "steps": 8, "cfg": 1.2},
    )
    assert values["width"] == 1024
    assert values["height"] == 1024


def test_is_arena_request():
    assert is_arena_request(
        ImageJobInput(prompt="x", mode=ImageMode.ARENA, metadata={"arena_slot": "b"})
    )
    assert not is_arena_request(ImageJobInput(prompt="x", mode=ImageMode.GENERATE))


def test_normalize_arena_resolution_strips_workflow_aspect():
    request = ImageJobInput(
        prompt="test",
        mode=ImageMode.GENERATE,
        size="768x768",
        metadata={"aspect": "9:16", "workflow_id": "wf"},
    )
    normalized = normalize_arena_resolution(request)
    assert normalized.mode == ImageMode.ARENA
    assert normalized.size == "768x768"
    assert normalized.metadata["arena_width"] == 768
    assert normalized.metadata["arena_height"] == 768
    assert "aspect" not in normalized.metadata


def test_inject_request_arena_binds_all_dimension_nodes():
    from maya_image.comfy_graphs import create_ideogram4_graph

    graph = create_ideogram4_graph(width=512, height=512)
    request = normalize_arena_resolution(
        ImageJobInput(
            prompt="test",
            mode=ImageMode.ARENA,
            size="896x896",
            metadata={"arena_slot": "a"},
        )
    )
    result = inject_request(graph, [], request, params={"aspect": "1:1"})
    assert result["8"]["inputs"]["width"] == 896
    assert result["8"]["inputs"]["height"] == 896
    assert result["11"]["inputs"]["width"] == 896
    assert result["11"]["inputs"]["height"] == 896


def test_auto_bind_anima_graph():
    graph = create_anima_t2i_graph()
    bindings = auto_bind(graph)
    keys = {b["key"] for b in bindings}
    assert "prompt" in keys
    assert "width" in keys
    assert "steps" in keys
