"""Contract tests for dashboard chat turn deduplication fixes."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONVERSATION_JS = ROOT / "apps/dashboard/js/mayaConversation.js"
TOOLS_PANEL_JS = ROOT / "apps/dashboard/js/mayaToolsPanel.js"
CONVERSATION_HTML = ROOT / "apps/dashboard/conversation.html"
SETTINGS_HTML = ROOT / "apps/dashboard/settings.html"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_ensure_operator_turn_uses_find_by_text() -> None:
    content = _read(CONVERSATION_JS)
    start = content.index("function _ensureOperatorTurn(")
    end = content.index("function _applyChatHttpResponse(", start)
    block = content[start:end]
    assert "_findOperatorTurnByText(store, text)" in block
    assert "last?.role === \"operator\"" not in block


def test_apply_cmd_response_uses_find_by_text() -> None:
    content = _read(CONVERSATION_JS)
    start = content.index("  if (data.ok) {")
    end = content.index("    _upsertCmdMayaTurn(store, {", start)
    block = content[start:end]
    assert "_findOperatorTurnByText(store, operatorText)" in block
    assert "lastOp?.role === \"operator\"" not in block


def test_sse_handled_corr_guard_present() -> None:
    content = _read(CONVERSATION_JS)
    assert "_sseHandledCorrIds" in content
    assert "function _sseAlreadyHandledForHttp(" in content
    assert "function _markSseHandledCorr(" in content
    assert "_sseAlreadyHandledForHttp(this, data.corr_id, text)" in content


def test_apply_chat_http_skips_when_sse_handled() -> None:
    content = _read(CONVERSATION_JS)
    start = content.index("function _applyChatHttpResponse(")
    end = content.index("function _applyCmdResponse(", start)
    block = content[start:end]
    assert "_sseAlreadyHandledForHttp(store, corrId, operatorText)" in block


def test_tools_panel_unsubscribes_before_resubscribe() -> None:
    content = _read(TOOLS_PANEL_JS)
    init_start = content.index("init() {")
    init_end = content.index("destroy()", init_start)
    block = content[init_start:init_end]
    assert "if (this._unsub)" in block
    assert "this._unsub();" in block


def test_tools_panel_init_returns_cleanup() -> None:
    content = _read(TOOLS_PANEL_JS)
    assert "return () => this.destroy();" in content


def test_tools_panel_wires_init_on_dashboard_pages() -> None:
    assert 'x-data="mayaToolsPanel()" x-init="init()"' in _read(CONVERSATION_HTML)
    assert 'x-data="mayaToolsPanel()" x-init="init()"' in _read(SETTINGS_HTML)


def test_tools_panel_dedupes_consecutive_log_lines() -> None:
    content = _read(TOOLS_PANEL_JS)
    assert "if (this.toolLog[0] === entry) return;" in content
