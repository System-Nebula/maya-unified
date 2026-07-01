"""Arena side-by-side composite layout."""

from pathlib import Path

from PIL import Image

from maya_image.arena_layout import build_placeholder_panel, build_side_by_side


def test_build_placeholder_panel_size():
    panel = build_placeholder_panel("A", size=(400, 300))
    assert panel.size == (400, 300)


def test_build_side_by_side_placeholder_only(tmp_path: Path):
    out = build_side_by_side(None, None, output_dir=tmp_path)
    assert out.is_file()
    with Image.open(out) as img:
        assert img.width > 500
        assert img.height >= 512


def test_build_side_by_side_left_only(tmp_path: Path):
    left_path = tmp_path / "left.png"
    Image.new("RGB", (640, 512), color=(255, 0, 0)).save(left_path)
    out = build_side_by_side(left_path, None, output_dir=tmp_path)
    with Image.open(out) as img:
        assert img.width > 640


def test_build_side_by_side_both_ready(tmp_path: Path):
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGB", (512, 512), color=(255, 0, 0)).save(left)
    Image.new("RGB", (512, 512), color=(0, 0, 255)).save(right)
    out = build_side_by_side(left, right, output_dir=tmp_path)
    with Image.open(out) as img:
        assert img.size == (1025, 512)


def test_build_side_by_side_equal_panels_mixed_aspect(tmp_path: Path):
    left = tmp_path / "left.png"
    right = tmp_path / "right.png"
    Image.new("RGB", (576, 1024), color=(255, 0, 0)).save(left)
    Image.new("RGB", (1024, 1024), color=(0, 0, 255)).save(right)
    out = build_side_by_side(left, right, output_dir=tmp_path)
    with Image.open(out) as img:
        assert img.size == (1025, 512)
