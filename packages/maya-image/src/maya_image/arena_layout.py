"""Side-by-side composite images for Discord arena battles."""

from __future__ import annotations

import uuid
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

_DEFAULT_PANEL = (512, 512)
_MAX_TOTAL_WIDTH = 2048
_PLACEHOLDER_BG = (48, 52, 58)
_PLACEHOLDER_FG = (185, 190, 198)
_DIVIDER = (72, 78, 88)
_BADGE_BG = (30, 33, 38, 200)


def _load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    try:
        return ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", size)
    except OSError:
        return ImageFont.load_default()


def build_placeholder_panel(
    label: str,
    *,
    size: tuple[int, int] = _DEFAULT_PANEL,
    status_text: str = "Generating…",
) -> Image.Image:
    """Gray panel shown while a slot is still rendering or failed."""
    img = Image.new("RGB", size, _PLACEHOLDER_BG)
    draw = ImageDraw.Draw(img)
    title_font = _load_font(28)
    body_font = _load_font(20)
    draw.text((24, 24), label, fill=_PLACEHOLDER_FG, font=title_font)
    draw.text((24, size[1] // 2 - 10), status_text, fill=_PLACEHOLDER_FG, font=body_font)
    return img


def _fit_image(path: Path, panel_size: tuple[int, int]) -> Image.Image:
    """Center-crop resize to an exact panel box (object-fit: cover)."""
    target_w, target_h = panel_size
    with Image.open(path) as raw:
        img = raw.convert("RGB")
    scale = max(target_w / img.width, target_h / img.height)
    new_w = max(1, int(img.width * scale + 0.5))
    new_h = max(1, int(img.height * scale + 0.5))
    img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
    left = max(0, (new_w - target_w) // 2)
    top = max(0, (new_h - target_h) // 2)
    return img.crop((left, top, left + target_w, top + target_h))


def _draw_badge(img: Image.Image, label: str) -> None:
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)
    font = _load_font(22)
    pad = 10
    text_bbox = draw.textbbox((0, 0), label, font=font)
    box_w = text_bbox[2] - text_bbox[0] + pad * 2
    box_h = text_bbox[3] - text_bbox[1] + pad * 2
    draw.rectangle((12, 12, 12 + box_w, 12 + box_h), fill=_BADGE_BG)
    draw.text((12 + pad, 12 + pad - text_bbox[1]), label, fill=(240, 240, 240), font=font)
    img.paste(overlay, (0, 0), overlay)


def _panel_for_slot(
    image_path: Path | None,
    *,
    label: str,
    placeholder_text: str,
    panel_size: tuple[int, int],
) -> Image.Image:
    if image_path is not None and image_path.is_file():
        panel = _fit_image(image_path, panel_size)
        _draw_badge(panel, label)
        return panel
    return build_placeholder_panel(label, size=panel_size, status_text=placeholder_text)


def build_side_by_side(
    left: Path | None,
    right: Path | None,
    *,
    left_label: str = "A",
    right_label: str = "B",
    left_placeholder: str = "Generating…",
    right_placeholder: str = "Generating…",
    panel_size: tuple[int, int] = _DEFAULT_PANEL,
    output_dir: Path | None = None,
) -> Path:
    """Stitch two panels horizontally; write PNG and return its path."""
    left_panel = _panel_for_slot(
        left,
        label=left_label,
        placeholder_text=left_placeholder,
        panel_size=panel_size,
    )
    right_panel = _panel_for_slot(
        right,
        label=right_label,
        placeholder_text=right_placeholder,
        panel_size=panel_size,
    )

    total_width = left_panel.width + 1 + right_panel.width
    height = max(left_panel.height, right_panel.height)
    if total_width > _MAX_TOTAL_WIDTH:
        scale = _MAX_TOTAL_WIDTH / total_width
        left_panel = left_panel.resize(
            (max(1, int(left_panel.width * scale)), max(1, int(left_panel.height * scale))),
            Image.Resampling.LANCZOS,
        )
        right_panel = right_panel.resize(
            (max(1, int(right_panel.width * scale)), max(1, int(right_panel.height * scale))),
            Image.Resampling.LANCZOS,
        )
        total_width = left_panel.width + 1 + right_panel.width
        height = max(left_panel.height, right_panel.height)

    canvas = Image.new("RGB", (total_width, height), _DIVIDER)
    canvas.paste(left_panel, (0, 0))
    canvas.paste(right_panel, (left_panel.width + 1, 0))

    out_dir = output_dir or Path("/tmp/maya-arena")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"arena-{uuid.uuid4().hex}.png"
    canvas.save(out_path, format="PNG")
    return out_path
