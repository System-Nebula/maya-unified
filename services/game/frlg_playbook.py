"""FireRed/LeafGreen guidance adapted from vision-only play (inspired by gpt-play-pokemon-firered)."""

from __future__ import annotations

# Ordered story beats — used as context, not hard gates (we have no RAM reader).
STORY_MILESTONES: list[str] = [
    "Leave player bedroom (walk down to stairs; ignore NES on rug)",
    "Exit house → Pallet Town",
    "Visit Oak's lab → choose starter Pokémon",
    "Rival battle → Route 1 → Viridian City",
    "Viridian Forest → Pewter City → Boulder Badge",
    "Mt. Moon → Cerulean → Cascade Badge",
    "Through Rock Tunnel → Lavender → Celadon → Vermilion",
    "S.S. Anne → Cut → Safari Zone → Fuchsia",
    "Silph Co. → Saffron → Marsh Badge",
    "Cinnabar → Blaine → Seafoam → Giovanni",
    "Victory Road → Indigo Plateau → Elite Four → Champion",
]

SCREEN_STATE_GUIDE = """
### Screen state (read the screenshot every turn)
| What you see | What to do |
|--------------|------------|
| **Dialogue text box** at bottom | `advance_dialog` to clear text, OR one `press_a` if text is still printing |
| **Overworld** (no text box, can walk) | `press_up/down/left/right` to move — do NOT mash A |
| **Menu / cursor** on options | Arrows to move highlight, then `press_a` once |
| **Battle** | Arrows in fight menu, `advance_dialog` after picking a move |
| **Wrong minigame** (NES, slots) | `press_b` or walk away with arrows — never loop A |

### Anti-loop (critical)
- If the same line of dialogue or object interaction repeats, **stop pressing A** — walk away with arrows.
- Never pick `wait` twice in a row; always press a button.
- #1 loop trap: interacting with the same object (NES, NPC) while facing it — **turn and walk**.
- Prefer exploration over backtracking when unsure.

### Elite Four run
Primary goal: defeat all Elite Four + Champion (Gary). Legendaries are optional side content.
Save before gyms; grind if team is underleveled.
"""


def milestone_context(*, goal: str = "", goal_progress: str = "", turn: int = 0) -> str:
    """Short milestone block for the vision prompt."""
    lines = ["### Story milestones (FireRed)", "Work toward the next unchecked step:"]
    for i, step in enumerate(STORY_MILESTONES, start=1):
        lines.append(f"{i}. {step}")
    if goal:
        lines.append(f"\n**Your mission:** {goal}")
    if goal_progress:
        lines.append(f"**Last progress note:** {goal_progress}")
    if turn:
        lines.append(f"**Turn:** {turn}")
    return "\n".join(lines)
