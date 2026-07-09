"""FireRed/LeafGreen name-grid navigation — deterministic name spelling + backspace.

Grid layout from pret/pokefirered ``naming_screen.c`` (KBCOL_COUNT=8, KBROW_COUNT=4).
Column 8 is the side button column (page / back / OK); OK is reached at row 3 col 7
then one more right onto the OK button.
"""

from __future__ import annotations

# Uppercase page — each row is exactly 8 cells (spaces and punctuation included).
_FRLG_ROWS: tuple[str, ...] = (
    "ABCDEF .",
    "GHIJKL ,",
    "MNOPQRS ",
    "TUVWXYZ ",
)

_FRLG_POSITIONS: dict[str, tuple[int, int]] = {}
for _row, _line in enumerate(_FRLG_ROWS):
    for _col, _ch in enumerate(_line):
        if _ch.strip() and _ch not in _FRLG_POSITIONS:
            _FRLG_POSITIONS[_ch] = (_row, _col)

_EMPTY_NAME_MARKERS = frozenset({
    "",
    "EMPTY",
    "NONE",
    "BLANK",
    "N/A",
    "NA",
    "NULL",
    "—",
    "-",
    "ENTERED",
    "LETTERS",
    "LETTERS_IN_BOX",
    "LETTERS_OR_EMPTY",
    "LETTERS_OR_EMPTY_STRING",
    "TARGET",
})


def normalize_entered_name(raw: str | None) -> str:
    """Map vision placeholders to a true empty name field."""
    text = (raw or "").strip().upper()
    if text in _EMPTY_NAME_MARKERS:
        return ""
    return text


def grid_pos(letter: str) -> tuple[int, int]:
    ch = (letter or "").strip().upper()
    if ch not in _FRLG_POSITIONS:
        raise ValueError(f"letter {letter!r} not on FRLG name grid")
    return _FRLG_POSITIONS[ch]


def moves_between(
    start: tuple[int, int],
    end: tuple[int, int],
    *,
    confirm: bool = True,
) -> list[str]:
    """Arrow moves from start cell to end cell, optional press_a to select."""
    r0, c0 = start
    r1, c1 = end
    out: list[str] = []
    if r1 > r0:
        out.extend(["press_down"] * (r1 - r0))
    elif r1 < r0:
        out.extend(["press_up"] * (r0 - r1))
    if c1 > c0:
        out.extend(["press_right"] * (c1 - c0))
    elif c1 < c0:
        out.extend(["press_left"] * (c0 - c1))
    if confirm:
        out.append("press_a")
    return out


def moves_to_ok_button(start: tuple[int, int]) -> list[str]:
    """Navigate from a letter cell to the OK side button and confirm."""
    r, c = start
    out: list[str] = []
    if r < 3:
        out.extend(["press_down"] * (3 - r))
    elif r > 3:
        out.extend(["press_up"] * (r - 3))
    if c < 7:
        out.extend(["press_right"] * (7 - c))
    elif c > 7:
        out.extend(["press_left"] * (c - 7))
  # Row 3 col 7 → one more right lands on OK (button column).
    out.append("press_right")
    out.append("press_a")
    return out


def plan_name_entry(
    name: str,
    *,
    start_pos: tuple[int, int] = (0, 0),
    confirm_end: bool = True,
) -> list[str]:
    """Full action sequence to spell `name` and confirm on OK."""
    text = (name or "").strip().upper()
    if not text:
        return []
    pos = start_pos
    actions: list[str] = []
    for ch in text:
        target = grid_pos(ch)
        actions.extend(moves_between(pos, target))
        pos = target
    if confirm_end:
        actions.extend(moves_to_ok_button(pos))
    return actions


def plan_backspace(count: int) -> list[str]:
    """B button on the naming screen deletes via the side back button — use press_b."""
    n = max(0, int(count))
    return ["press_b"] * n


def plan_name_suffix(
    current: str,
    target: str,
    *,
    start_pos: tuple[int, int] = (0, 0),
) -> list[str]:
    """Type only the remaining letters when `current` is a correct prefix of `target`."""
    cur = normalize_entered_name(current)
    tgt = (target or "").strip().upper()
    if not tgt:
        return []
    if cur == tgt:
        if not cur:
            return []
        return moves_to_ok_button(grid_pos(cur[-1]))
    if cur and not tgt.startswith(cur):
        return plan_name_fix(cur, tgt, start_pos=start_pos)
    if not cur:
        return plan_name_entry(tgt, start_pos=start_pos)

    pos = grid_pos(cur[-1])
    actions: list[str] = []
    for ch in tgt[len(cur) :]:
        target_cell = grid_pos(ch)
        actions.extend(moves_between(pos, target_cell))
        pos = target_cell
    actions.extend(moves_to_ok_button(pos))
    return actions


def plan_name_fix(
    current: str,
    target: str,
    *,
    start_pos: tuple[int, int] = (0, 0),
) -> list[str]:
    """Clear a wrong/partial name with B, then spell the target from scratch."""
    cur = normalize_entered_name(current)
    tgt = (target or "").strip().upper()
    if not tgt:
        return []
    if cur == tgt:
        return []
    if cur and tgt.startswith(cur):
        return plan_name_suffix(cur, tgt, start_pos=start_pos)
    actions: list[str] = []
    if cur:
        actions.extend(plan_backspace(len(cur)))
    actions.extend(plan_name_entry(tgt, start_pos=start_pos))
    return actions


def take_naming_chunk(queue: list[str], *, max_arrow_run: int = 3) -> list[str]:
    """Take the next naming inputs — never burst past press_a / press_b."""
    if not queue:
        return []
    chunk: list[str] = []
    arrow_run = 0
    while queue:
        step = queue[0]
        if step in ("press_a", "press_b"):
            if chunk:
                break
            chunk.append(queue.pop(0))
            break
        if not step.startswith("press_"):
            break
        if arrow_run >= max(1, max_arrow_run):
            break
        chunk.append(queue.pop(0))
        arrow_run += 1
    return chunk


def update_cursor(cursor: tuple[int, int], action: str) -> tuple[int, int]:
    r, c = cursor
    if action == "press_up":
        r -= 1
    elif action == "press_down":
        r += 1
    elif action == "press_left":
        c -= 1
    elif action == "press_right":
        c += 1
    return (r, c)
