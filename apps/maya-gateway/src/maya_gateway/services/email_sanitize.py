"""Sanitize stored email HTML for safe same-origin serving (SEC-007)."""

from __future__ import annotations

import html
import re
from html.parser import HTMLParser

_ALLOWED_TAGS = frozenset(
    {
        "a",
        "b",
        "blockquote",
        "br",
        "caption",
        "code",
        "div",
        "em",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "hr",
        "i",
        "img",
        "li",
        "ol",
        "p",
        "pre",
        "span",
        "strong",
        "table",
        "tbody",
        "td",
        "th",
        "thead",
        "tr",
        "u",
        "ul",
    }
)

_ALLOWED_ATTRS = {
    "a": frozenset({"href", "title"}),
    "img": frozenset({"src", "alt", "title", "width", "height"}),
    "*": frozenset({"class"}),
}

_SAFE_URL = re.compile(r"^(https?:|mailto:|#|/)", re.I)
_EVENT_ATTR = re.compile(r"^on", re.I)


class _Sanitizer(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._out: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag_l = tag.lower()
        if self._skip_depth or tag_l not in _ALLOWED_TAGS:
            if tag_l in {"script", "style", "iframe", "object", "embed", "form", "svg"}:
                self._skip_depth += 1
            return
        allowed = _ALLOWED_ATTRS.get(tag_l, frozenset()) | _ALLOWED_ATTRS["*"]
        cleaned: list[str] = []
        for name, value in attrs:
            if not name or _EVENT_ATTR.match(name):
                continue
            n = name.lower()
            if n not in allowed:
                continue
            val = value or ""
            if n in {"href", "src"} and not _SAFE_URL.match(val.strip()):
                continue
            cleaned.append(f'{html.escape(n)}="{html.escape(val, quote=True)}"')
        attr_s = (" " + " ".join(cleaned)) if cleaned else ""
        if tag_l in {"br", "hr", "img"}:
            self._out.append(f"<{tag_l}{attr_s} />")
        else:
            self._out.append(f"<{tag_l}{attr_s}>")

    def handle_endtag(self, tag: str) -> None:
        tag_l = tag.lower()
        if tag_l in {"script", "style", "iframe", "object", "embed", "form", "svg"}:
            if self._skip_depth:
                self._skip_depth -= 1
            return
        if self._skip_depth or tag_l not in _ALLOWED_TAGS or tag_l in {"br", "hr", "img"}:
            return
        self._out.append(f"</{tag_l}>")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        self._out.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._out.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._skip_depth:
            return
        self._out.append(f"&#{name};")

    def result(self) -> str:
        return "".join(self._out)


def sanitize_email_html(raw: str) -> str:
    """Strict allowlist sanitizer — strips scripts, forms, iframes, event handlers."""
    parser = _Sanitizer()
    try:
        parser.feed(raw or "")
        parser.close()
    except Exception:  # noqa: BLE001
        return f"<pre>{html.escape(raw or '')}</pre>"
    return parser.result()


ARTIFACT_CSP = (
    "sandbox; default-src 'none'; img-src https: data:; style-src 'unsafe-inline'; "
    "base-uri 'none'; form-action 'none'"
)
