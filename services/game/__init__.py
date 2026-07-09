"""Vision game bridge — Neuro-compatible game sessions."""

__all__ = ["game_hub"]


def __getattr__(name: str):
    if name == "game_hub":
        from services.game.neuro_server import game_hub as hub

        return hub
    raise AttributeError(name)
