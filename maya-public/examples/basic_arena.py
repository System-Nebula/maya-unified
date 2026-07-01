"""Basic arena interaction example."""

import httpx

BASE = "http://localhost:8080"


def add_candidate(name: str, provider: str, voice_id: str) -> str:
    r = httpx.post(
        f"{BASE}/api/arena/candidates",
        json={"name": name, "provider": provider, "voice_id": voice_id},
    )
    r.raise_for_status()
    return r.json()["id"]


def create_battle(a_id: str, b_id: str, prompt: str) -> str:
    r = httpx.post(
        f"{BASE}/api/arena/battles",
        json={"candidate_a_id": a_id, "candidate_b_id": b_id, "prompt": prompt},
    )
    r.raise_for_status()
    return r.json()["id"]


def vote(battle_id: str, choice: str) -> None:
    r = httpx.post(
        f"{BASE}/api/arena/battles/{battle_id}/vote",
        json={"choice": choice},
    )
    r.raise_for_status()


if __name__ == "__main__":
    a = add_candidate("Alice", "fal", "voice-a")
    b = add_candidate("Bob", "fal", "voice-b")
    battle = create_battle(a, b, "Who sounds more natural?")
    print(f"Battle created: {battle}")
