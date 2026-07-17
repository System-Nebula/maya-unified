"""Generate Maya DESIGN.md demo sites (companion / memory / settings)."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DESIGN = ROOT / "design-md"

BRANDS = [
    ("elevenlabs", "ElevenLabs", "warm", "Voice-first cinematic companion"),
    ("linear", "Linear", "dense", "Precise operator density"),
    ("raycast", "Raycast", "dense", "Command-palette energy"),
    ("cursor", "Cursor", "dense", "AI-native chrome"),
    ("voltagent", "VoltAgent", "dense", "Void-black agent terminal"),
    ("spotify", "Spotify", "warm", "Music-led player theater"),
    ("vercel", "Vercel", "dense", "Monochrome operator portal"),
    ("supabase", "Supabase", "dense", "Emerald data dashboard"),
    ("resend", "Resend", "dense", "Quiet dark + mono"),
    ("stripe", "Stripe", "warm", "Polished SaaS clarity"),
    ("ollama", "Ollama", "dense", "Local LLM terminal"),
    ("sentry", "Sentry", "dense", "Dense monitoring chrome"),
]

# Curated dark-operator tokens per brand (DESIGN.md-faithful accents; dark-first demos).
FALLBACK = {
    "elevenlabs": {
        # Faithful to DESIGN.md: off-white editorial canvas, ink pill CTAs
        "bg": "#f5f5f5",
        "surface": "#ffffff",
        "surface2": "#f0efed",
        "text": "#0c0a09",
        "muted": "#777169",
        "accent": "#292524",
        "border": "#e7e5e4",
        "on_accent": "#ffffff",
        "radius": "16px",
        "font": "Inter, system-ui, sans-serif",
        "display": "'EB Garamond', 'Times New Roman', Georgia, serif",
    },
    "linear": {
        "bg": "#010102",
        "surface": "#0f1011",
        "surface2": "#18191a",
        "text": "#f7f8f8",
        "muted": "#8a8f98",
        "accent": "#5e6ad2",
        "border": "#23252a",
        "on_accent": "#ffffff",
        "radius": "8px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
    "raycast": {
        "bg": "#07080a",
        "surface": "#0d0d0d",
        "surface2": "#121212",
        "text": "#f4f4f6",
        "muted": "#9c9c9d",
        "accent": "#ff6161",
        "border": "#242728",
        "on_accent": "#ffffff",
        "radius": "10px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
    "cursor": {
        "bg": "#14140f",
        "surface": "#1c1b16",
        "surface2": "#26251e",
        "text": "#f7f7f4",
        "muted": "#a09c92",
        "accent": "#f54e00",
        "border": "#3a3932",
        "on_accent": "#ffffff",
        "radius": "10px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
    "voltagent": {
        "bg": "#101010",
        "surface": "#1a1a1a",
        "surface2": "#222222",
        "text": "#f2f2f2",
        "muted": "#8b949e",
        "accent": "#00d992",
        "border": "#3d3a39",
        "on_accent": "#101010",
        "radius": "8px",
        "font": "Inter, ui-monospace, monospace",
        "display": "Inter, system-ui, sans-serif",
    },
    "spotify": {
        "bg": "#121212",
        "surface": "#181818",
        "surface2": "#282828",
        "text": "#ffffff",
        "muted": "#b3b3b3",
        "accent": "#1ed760",
        "border": "#4d4d4d",
        "on_accent": "#121212",
        "radius": "999px",
        "font": "Helvetica Neue, Helvetica, Arial, sans-serif",
        "display": "Helvetica Neue, Helvetica, Arial, sans-serif",
    },
    "vercel": {
        "bg": "#000000",
        "surface": "#0a0a0a",
        "surface2": "#111111",
        "text": "#ededed",
        "muted": "#888888",
        "accent": "#ffffff",
        "border": "#333333",
        "on_accent": "#000000",
        "radius": "8px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
    "supabase": {
        "bg": "#1c1c1c",
        "surface": "#242424",
        "surface2": "#2e2e2e",
        "text": "#ededed",
        "muted": "#989898",
        "accent": "#3ecf8e",
        "border": "#363636",
        "on_accent": "#0f0f0f",
        "radius": "8px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
    "resend": {
        "bg": "#000000",
        "surface": "#0c0c0c",
        "surface2": "#141414",
        "text": "#fafafa",
        "muted": "#8a8a8a",
        "accent": "#ffffff",
        "border": "#262626",
        "on_accent": "#000000",
        "radius": "8px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, ui-monospace, monospace",
    },
    "stripe": {
        "bg": "#0a2540",
        "surface": "#0f2e4c",
        "surface2": "#163d63",
        "text": "#f6f9fc",
        "muted": "#adbdcc",
        "accent": "#635bff",
        "border": "#2a4a6a",
        "on_accent": "#ffffff",
        "radius": "12px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
    "ollama": {
        "bg": "#0d0d0d",
        "surface": "#171717",
        "surface2": "#1f1f1f",
        "text": "#f5f5f5",
        "muted": "#a3a3a3",
        "accent": "#ffffff",
        "border": "#2e2e2e",
        "on_accent": "#0d0d0d",
        "radius": "6px",
        "font": "Inter, ui-monospace, monospace",
        "display": "Inter, system-ui, sans-serif",
    },
    "sentry": {
        "bg": "#150f23",
        "surface": "#1f1633",
        "surface2": "#2b2145",
        "text": "#f0ecf5",
        "muted": "#bdb8c0",
        "accent": "#fa7faa",
        "border": "#362d59",
        "on_accent": "#150f23",
        "radius": "8px",
        "font": "Inter, system-ui, sans-serif",
        "display": "Inter, system-ui, sans-serif",
    },
}


def parse_colors(text: str) -> dict[str, str]:
    m = re.search(r"^colors:\n((?:  .+\n)+)", text, re.M)
    colors: dict[str, str] = {}
    if not m:
        return colors
    for line in m.group(1).splitlines():
        mm = re.match(r'  ([^:]+):\s*"([^"]+)"', line)
        if mm:
            colors[mm.group(1).strip()] = mm.group(2).strip()
    return colors


def pick(colors: dict[str, str], *keys: str, default: str = "") -> str:
    for k in keys:
        if k in colors:
            return colors[k]
    return default


def normalize(slug: str, colors: dict[str, str]) -> dict[str, str]:
    """Always start from curated dark-operator FALLBACK; overlay safe DESIGN.md accents."""
    tokens = dict(FALLBACK[slug])
    # Prefer brand primary / soft primary; decorative accent-* only as last resort
    accent_keys = (
        "primary-soft",
        "primary-deep",
        "primary",
        "gradient-mint",
        "accent-red",
        "accent-blue",
        "accent-orange",
        "accent-pink",
        "accent-lime",
    )
    bad_accents = {
        "#000000",
        "#000",
        "#ffffff",
        "#fff",
        "#fcfdff",
        "#171717",
        "#150f23",
        "#292524",
        "#010102",
        "#0c0a09",
    }
    for key in accent_keys:
        if key not in colors:
            continue
        cand = colors[key]
        if cand.lower() not in bad_accents:
            tokens["accent"] = cand
            break
    muted = pick(colors, "mute", "muted", "ink-subtle", "on-dark-muted", "body", "ash")
    if muted and not muted.startswith("rgba") and muted.lower() not in {"#292524", "#171717", "#000000"}:
        tokens["muted"] = muted
    border = pick(colors, "hairline", "hairline-violet", "hairline-strong")
    # Skip light marketing hairlines on dark demos
    if border and not border.startswith("rgba"):
        br = border.lower().lstrip("#")
        if len(br) == 6:
            r, g, b = int(br[0:2], 16), int(br[2:4], 16), int(br[4:6], 16)
            if (r + g + b) / 3 < 140:
                tokens["border"] = border
    # Keep curated on_accent from FALLBACK (DESIGN.md on-primary often assumes light CTAs)
    return tokens


CSS_BASE = """/* Shared demo chrome — brand tokens override :root below */
*,
*::before,
*::after {{ box-sizing: border-box; }}
html, body {{
  margin: 0;
  min-height: 100%;
  background: var(--demo-bg);
  color: var(--demo-text);
  font-family: var(--demo-font);
}}
a {{ color: inherit; text-decoration: none; }}
button, input, select, textarea {{ font: inherit; color: inherit; }}
.demo-shell {{
  min-height: 100vh;
  display: flex;
  flex-direction: column;
  padding-bottom: 72px;
}}
.demo-top {{
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 14px 22px;
  border-bottom: 1px solid var(--demo-border);
  background: color-mix(in srgb, var(--demo-surface) 92%, transparent);
  backdrop-filter: blur(12px);
  position: sticky;
  top: 0;
  z-index: 20;
}}
.demo-brand {{
  font-family: var(--demo-display);
  font-weight: 600;
  letter-spacing: -0.03em;
  font-size: 1.05rem;
}}
.demo-brand span {{ color: var(--demo-muted); font-weight: 400; margin-left: 8px; font-size: 0.85rem; }}
.demo-primary-nav {{ display: flex; gap: 6px; margin-left: auto; flex-wrap: wrap; }}
.demo-primary-nav a {{
  padding: 8px 14px;
  border-radius: calc(var(--demo-radius) / 2);
  color: var(--demo-muted);
  border: 1px solid transparent;
}}
.demo-primary-nav a:hover {{ color: var(--demo-text); background: var(--demo-surface2); }}
.demo-primary-nav a.is-active {{
  color: var(--demo-on-accent);
  background: var(--demo-accent);
  border-color: transparent;
}}
.demo-main {{
  flex: 1;
  width: min(1200px, calc(100% - 32px));
  margin: 0 auto;
  padding: 24px 0 40px;
}}
.demo-footer {{
  position: fixed;
  left: 0; right: 0; bottom: 0;
  z-index: 40;
  display: flex;
  gap: 8px;
  align-items: center;
  padding: 10px 14px;
  background: color-mix(in srgb, var(--demo-bg) 88%, black);
  border-top: 1px solid var(--demo-border);
  overflow-x: auto;
}}
.demo-footer .label {{
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--demo-muted);
  white-space: nowrap;
}}
.demo-footer a, .demo-footer button {{
  border: 1px solid var(--demo-border);
  background: var(--demo-surface);
  color: var(--demo-muted);
  border-radius: 999px;
  padding: 6px 10px;
  font-size: 12px;
  cursor: pointer;
  white-space: nowrap;
}}
.demo-footer a.is-active, .demo-footer button.is-active {{
  color: var(--demo-on-accent);
  background: var(--demo-accent);
  border-color: transparent;
}}
.panel {{
  background: var(--demo-surface);
  border: 1px solid var(--demo-border);
  border-radius: var(--demo-radius);
  padding: 16px;
}}
.panel h2, .panel h3 {{ margin: 0 0 10px; font-family: var(--demo-display); letter-spacing: -0.02em; }}
.muted {{ color: var(--demo-muted); }}
.btn {{
  display: inline-flex;
  align-items: center;
  gap: 8px;
  border: none;
  cursor: pointer;
  background: var(--demo-accent);
  color: var(--demo-on-accent);
  border-radius: var(--demo-radius);
  padding: 10px 16px;
  font-weight: 600;
}}
.btn.ghost {{
  background: transparent;
  color: var(--demo-text);
  border: 1px solid var(--demo-border);
}}
.chip {{
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 4px 10px;
  border-radius: 999px;
  border: 1px solid var(--demo-border);
  color: var(--demo-muted);
  font-size: 12px;
}}
.chip.ok {{ color: var(--demo-accent); border-color: color-mix(in srgb, var(--demo-accent) 40%, var(--demo-border)); }}
.grid-2 {{ display: grid; gap: 16px; grid-template-columns: repeat(2, minmax(0, 1fr)); }}
.grid-3 {{ display: grid; gap: 16px; grid-template-columns: repeat(3, minmax(0, 1fr)); }}
@media (max-width: 900px) {{
  .grid-2, .grid-3 {{ grid-template-columns: 1fr; }}
  .demo-primary-nav {{ margin-left: 0; width: 100%; }}
  .demo-top {{ flex-wrap: wrap; }}
}}
.layout-warm .hero-title {{ font-size: clamp(2rem, 4vw, 3.2rem); font-weight: 300; line-height: 1.1; }}
.layout-dense .hero-title {{ font-size: clamp(1.4rem, 2.4vw, 2rem); font-weight: 600; line-height: 1.15; }}
.msg {{
  padding: 10px 12px;
  border-radius: calc(var(--demo-radius) / 1.5);
  margin: 8px 0;
  background: var(--demo-surface2);
  border: 1px solid var(--demo-border);
}}
.msg.user {{ border-left: 3px solid var(--demo-accent); }}
.msg.ai {{ border-left: 3px solid color-mix(in srgb, var(--demo-muted) 50%, transparent); }}
.msg .meta {{ font-size: 11px; color: var(--demo-muted); margin-top: 6px; }}
.row {{ display: flex; gap: 10px; align-items: center; }}
.row.between {{ justify-content: space-between; }}
.stack {{ display: flex; flex-direction: column; gap: 12px; }}
.table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
.table th, .table td {{ text-align: left; padding: 10px 8px; border-bottom: 1px solid var(--demo-border); }}
.table th {{ color: var(--demo-muted); font-weight: 500; }}
.side-layout {{ display: grid; grid-template-columns: 220px 1fr; gap: 16px; }}
@media (max-width: 800px) {{ .side-layout {{ grid-template-columns: 1fr; }} }}
.settings-nav button {{
  display: block; width: 100%; text-align: left;
  background: transparent; border: 1px solid transparent;
  color: var(--demo-muted); padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 4px;
}}
.settings-nav button.is-active {{
  color: var(--demo-text); background: var(--demo-surface2); border-color: var(--demo-border);
}}
.field {{ margin-bottom: 14px; }}
.field label {{ display: block; font-size: 12px; color: var(--demo-muted); margin-bottom: 6px; }}
.field input, .field select, .field textarea {{
  width: 100%;
  background: var(--demo-bg);
  border: 1px solid var(--demo-border);
  border-radius: 8px;
  padding: 10px 12px;
}}
.waveform {{
  height: 48px;
  border-radius: 8px;
  background: linear-gradient(90deg,
    color-mix(in srgb, var(--demo-accent) 15%, transparent),
    color-mix(in srgb, var(--demo-accent) 55%, transparent),
    color-mix(in srgb, var(--demo-accent) 20%, transparent));
  position: relative;
  overflow: hidden;
}}
.waveform::after {{
  content: "";
  position: absolute; inset: 0;
  background: repeating-linear-gradient(90deg,
    transparent 0 6px,
    color-mix(in srgb, var(--demo-text) 18%, transparent) 6px 7px);
  opacity: 0.45;
}}
.avatar-orb {{
  width: 100%;
  aspect-ratio: 1;
  border-radius: calc(var(--demo-radius) * 1.2);
  background:
    radial-gradient(circle at 30% 30%, color-mix(in srgb, var(--demo-accent) 55%, white), transparent 45%),
    radial-gradient(circle at 70% 60%, color-mix(in srgb, var(--demo-accent) 35%, transparent), transparent 50%),
    var(--demo-surface2);
  border: 1px solid var(--demo-border);
}}
.tool-log {{
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  font-size: 12px;
  max-height: 180px;
  overflow: auto;
  background: var(--demo-bg);
  border: 1px solid var(--demo-border);
  border-radius: 8px;
  padding: 10px;
}}
.tool-log div {{ margin: 4px 0; color: var(--demo-muted); }}
.tool-log strong {{ color: var(--demo-accent); font-weight: 600; }}
.cta-row {{ display: flex; flex-wrap: wrap; gap: 10px; margin-top: 14px; }}
.section-title {{ margin: 8px 0 16px; }}
.section-title p {{ margin: 6px 0 0; color: var(--demo-muted); max-width: 52ch; }}
.badge-imp {{
  font-size: 11px; padding: 2px 8px; border-radius: 999px;
  background: color-mix(in srgb, var(--demo-accent) 18%, transparent);
  color: var(--demo-accent);
}}
"""


def css_for(slug: str, tokens: dict[str, str], tone: str) -> str:
    root = f""":root {{
  --demo-bg: {tokens['bg']};
  --demo-surface: {tokens['surface']};
  --demo-surface2: {tokens['surface2']};
  --demo-text: {tokens['text']};
  --demo-muted: {tokens['muted']};
  --demo-accent: {tokens['accent']};
  --demo-border: {tokens['border']};
  --demo-on-accent: {tokens['on_accent']};
  --demo-radius: {tokens['radius']};
  --demo-font: {tokens['font']};
  --demo-display: {tokens['display']};
}}
body.layout-{tone} {{ }}
"""
    brand_extras = {
        "elevenlabs": """
/* ElevenLabs DESIGN.md — editorial light canvas + atmospheric orbs */
body.layout-warm {
  background: var(--demo-bg);
  letter-spacing: 0.01em;
}
body.layout-warm::before,
body.layout-warm::after {
  content: "";
  position: fixed;
  pointer-events: none;
  z-index: 0;
  border-radius: 50%;
  filter: blur(60px);
  opacity: 0.55;
}
body.layout-warm::before {
  width: 420px; height: 420px; top: -80px; left: -60px;
  background: radial-gradient(circle, #a7e5d3 0%, transparent 70%);
}
body.layout-warm::after {
  width: 480px; height: 480px; top: 20%; right: -120px;
  background: radial-gradient(circle, #c8b8e0 0%, transparent 68%);
}
.demo-shell { position: relative; z-index: 1; }
.demo-top {
  background: rgba(245, 245, 245, 0.86);
  border-bottom-color: #e7e5e4;
}
.demo-brand {
  font-family: var(--demo-display);
  font-weight: 300;
  letter-spacing: -0.04em;
  font-size: 1.35rem;
}
.demo-primary-nav a {
  border-radius: 9999px;
  font-weight: 500;
  font-size: 15px;
}
.demo-primary-nav a.is-active {
  background: #292524;
  color: #ffffff;
}
.btn {
  border-radius: 9999px !important;
  font-weight: 500 !important;
  padding: 10px 20px !important;
  background: #292524 !important;
  color: #ffffff !important;
}
.btn.ghost {
  background: transparent !important;
  color: #0c0a09 !important;
  border: 1px solid #d6d3d1 !important;
}
.panel {
  background: #ffffff;
  border-color: #e7e5e4;
  border-radius: 16px;
  box-shadow: none;
  padding: 24px;
}
.panel h2, .panel h3, .hero-title {
  font-family: var(--demo-display);
  font-weight: 300;
  letter-spacing: -0.03em;
  color: #0c0a09;
}
.layout-warm .hero-title {
  font-size: clamp(2.4rem, 5vw, 3.6rem);
  line-height: 1.08;
  letter-spacing: -0.04em;
}
.section-title p { color: #4e4e4e; font-size: 16px; letter-spacing: 0.16px; }
.msg {
  background: #fafafa;
  border-color: #e7e5e4;
  border-radius: 12px;
}
.msg.user { border-left-color: #292524; }
.chip {
  background: #f0efed;
  border-color: transparent;
  color: #292524;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.06em;
  text-transform: uppercase;
}
.chip.ok { color: #292524; background: #f0efed; }
.avatar-orb {
  border-radius: 24px;
  border: none;
  background:
    radial-gradient(circle at 28% 32%, #a7e5d3, transparent 42%),
    radial-gradient(circle at 72% 28%, #f4c5a8, transparent 40%),
    radial-gradient(circle at 55% 78%, #c8b8e0, transparent 45%),
    radial-gradient(circle at 20% 75%, #a8c8e8, transparent 40%),
    #fafafa;
}
.waveform {
  background: linear-gradient(90deg, #a7e5d3, #f4c5a8, #c8b8e0, #a8c8e8);
  opacity: 0.85;
}
.waveform::after { opacity: 0.25; }
.tool-log {
  background: #fafafa;
  border-color: #e7e5e4;
  color: #4e4e4e;
}
.tool-log strong { color: #292524; }
.demo-footer {
  background: rgba(250, 250, 250, 0.94);
  border-top-color: #e7e5e4;
}
.demo-footer a.is-active {
  background: #292524;
  color: #fff;
}
.field input, .field select, .field textarea {
  background: #ffffff;
  border-color: #d6d3d1;
  color: #0c0a09;
  border-radius: 8px;
}
.badge-imp {
  background: #f0efed;
  color: #292524;
}
/* soft peach orb lower-left */
.demo-main::before {
  content: "";
  position: fixed;
  width: 360px; height: 360px;
  bottom: 40px; left: 10%;
  background: radial-gradient(circle, #f4c5a8 0%, transparent 70%);
  filter: blur(50px);
  opacity: 0.45;
  pointer-events: none;
  z-index: 0;
}
""",
        "spotify": """
.layout-warm .btn { text-transform: uppercase; letter-spacing: 0.12em; font-size: 12px; }
.player-art {
  width: 64px; height: 64px; border-radius: 8px;
  background: linear-gradient(135deg, #1ed760, #121212);
}
""",
        "raycast": """
.demo-brand {
  background: linear-gradient(90deg, #ff6363, #ffb86c, #50fa7b);
  -webkit-background-clip: text; background-clip: text; color: transparent;
}
""",
        "voltagent": """
.tool-log { border-color: color-mix(in srgb, var(--demo-accent) 35%, var(--demo-border)); }
""",
        "stripe": """
.layout-warm .panel {
  box-shadow: 0 24px 48px rgba(0,0,0,0.25);
}
""",
    }
    return root + CSS_BASE.format() + brand_extras.get(slug, "")


HTML_TMPL = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Maya Demo · {label} · {page_title}</title>
  <link rel="preconnect" href="https://fonts.googleapis.com" />
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
  <link href="https://fonts.googleapis.com/css2?family=EB+Garamond:wght@300;400;500&family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet" />
  <link rel="stylesheet" href="./demo.css" />
</head>
<body class="layout-{tone}" data-demo-brand="{slug}" data-demo-page="{page}">
  <div class="demo-shell">
    <header class="demo-top" data-demo-nav></header>
    <main class="demo-main" id="demo-app"></main>
  </div>
  <footer class="demo-footer" data-demo-footer></footer>
  <script src="../shared/maya-demo-content.js"></script>
  <script src="../shared/demo-nav.js"></script>
  <script src="../shared/demo-app.js"></script>
</body>
</html>
"""


HUB = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Maya · DESIGN.md Demo Hub</title>
  <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet" />
  <style>
    :root {{
      --bg: #0b0b0d; --card: #141418; --text: #f4f4f5; --muted: #a1a1aa; --line: #27272a; --accent: #60a5fa;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0; font-family: Inter, system-ui, sans-serif; background: var(--bg); color: var(--text);
      min-height: 100vh; padding: 40px 20px 80px;
    }}
    .wrap {{ width: min(1100px, 100%); margin: 0 auto; }}
    h1 {{ font-size: clamp(1.8rem, 3vw, 2.6rem); letter-spacing: -0.04em; margin: 0 0 8px; }}
    p.lead {{ color: var(--muted); max-width: 60ch; line-height: 1.5; }}
    .grid {{
      display: grid; gap: 14px; margin-top: 28px;
      grid-template-columns: repeat(auto-fill, minmax(240px, 1fr));
    }}
    a.card {{
      display: block; padding: 18px; border-radius: 14px; background: var(--card);
      border: 1px solid var(--line); color: inherit; text-decoration: none;
      transition: border-color .15s, transform .15s;
    }}
    a.card:hover {{ border-color: var(--accent); transform: translateY(-2px); }}
    a.card strong {{ display: block; margin-bottom: 6px; }}
    a.card span {{ color: var(--muted); font-size: 13px; line-height: 1.4; }}
    .rank {{ font-size: 11px; color: var(--accent); letter-spacing: 0.08em; text-transform: uppercase; }}
    .links {{ margin-top: 28px; display: flex; gap: 12px; flex-wrap: wrap; }}
    .links a {{
      color: var(--muted); border: 1px solid var(--line); padding: 8px 12px; border-radius: 999px; text-decoration: none;
    }}
    .note {{ margin-top: 18px; font-size: 13px; color: var(--muted); }}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>Maya DESIGN.md demos</h1>
    <p class="lead">
      Separate aesthetic demo sites inspired by brand DESIGN.md files.
      Each site includes Companion, Memory, and Settings — mock theater covering Maya’s surfaces.
      Production dashboard is unchanged.
    </p>
    <div class="grid">
{cards}
    </div>
    <div class="links">
      <a href="/dashboard/conversation.html">Open live Maya</a>
      <a href="/dashboard/memory.html">Live Memory</a>
      <a href="/dashboard/settings.html">Live Settings</a>
    </div>
    <p class="note">Temporary demo hub · /dashboard/demo/</p>
  </div>
</body>
</html>
"""


def main() -> None:
    shared = ROOT / "shared"
    shared.mkdir(parents=True, exist_ok=True)

    cards = []
    for i, (slug, label, tone, blurb) in enumerate(BRANDS, start=1):
        md = DESIGN / slug / "DESIGN.md"
        colors = parse_colors(md.read_text(encoding="utf-8")) if md.exists() else {}
        # ElevenLabs / Spotify: curated tokens must win (DESIGN.md light editorial / green player)
        if slug in {"elevenlabs", "spotify"}:
            tokens = dict(FALLBACK[slug])
        else:
            tokens = normalize(slug, colors)

        brand_dir = ROOT / slug
        brand_dir.mkdir(parents=True, exist_ok=True)
        (brand_dir / "demo.css").write_text(css_for(slug, tokens, tone), encoding="utf-8")
        for page, title in (("index", "Companion"), ("memory", "Memory"), ("settings", "Settings")):
            html = HTML_TMPL.format(
                label=label,
                page_title=title,
                tone=tone,
                slug=slug,
                page=page if page != "index" else "companion",
            )
            (brand_dir / f"{page}.html").write_text(html, encoding="utf-8")

        cards.append(
            f'      <a class="card" href="./{slug}/index.html"><div class="rank">#{i}</div>'
            f"<strong>{label}</strong><span>{blurb}</span></a>"
        )
        print(f"wrote {slug} accent={tokens['accent']} bg={tokens['bg']}")

    (ROOT / "index.html").write_text(HUB.format(cards="\n".join(cards)), encoding="utf-8")
    print("hub ok")


if __name__ == "__main__":
    main()
