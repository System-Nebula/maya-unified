"""AGE (Apache AGE / Cypher-in-Postgres) persistence for /imagine turns.

Each generation/edit/remix is recorded as an ``(:ImageTurn)`` node so we can
query the full creative lineage of any output. Remix chains are
``(t2)-[:DERIVED_FROM {strength}]->(t1)`` edges; reference images are
``(t)-[:REFERENCES]->(:RefImage)`` edges.

All writes are best-effort: failures are logged, never raised into the job flow.
These functions are synchronous (psycopg under AGE); call them from a thread
(``asyncio.to_thread``) like the arena session persistence does.
"""

from __future__ import annotations

from typing import Any, Optional

import structlog

from maya_image.graph_age import get_age, record_image_turn, update_turn_rating

logger = structlog.get_logger()

_GRAPH = "archive_graph"


def record_image_turn(
    *,
    turn_id: str,
    generation_id: str,
    provider: str,
    model: str,
    prompt_raw: str,
    image_url: str,
    prompt_expanded: Optional[str] = None,
    seed: Optional[int] = None,
    aspect: Optional[str] = None,
    action: str = "generate",
    discord_message_id: Optional[str] = None,
    parent_turn_id: Optional[str] = None,
    reference_urls: Optional[list[str]] = None,
    strength: Optional[float] = None,
    workflow_id: Optional[str] = None,
    source: Optional[str] = None,
    user_id: Optional[str] = None,
    graph_name: str = _GRAPH,
) -> bool:
    """MERGE an ImageTurn node and its lineage edges. Returns success."""
    try:
        age = get_age(graph_name=graph_name)
        age.execute_write(
            """
            MERGE (t:ImageTurn {turn_id: $turn_id})
            SET t.generation_id = $generation_id,
                t.provider = $provider,
                t.model = $model,
                t.prompt_raw = $prompt_raw,
                t.prompt_expanded = $prompt_expanded,
                t.seed = $seed,
                t.aspect = $aspect,
                t.image_url = $image_url,
                t.action = $action,
                t.discord_message_id = $discord_message_id,
                t.workflow_id = $workflow_id,
                t.source = $source,
                t.user_id = $user_id
            RETURN t.turn_id
            """,
            {
                "turn_id": turn_id,
                "generation_id": generation_id,
                "provider": provider,
                "model": model,
                "prompt_raw": prompt_raw,
                "prompt_expanded": prompt_expanded,
                "seed": seed,
                "aspect": aspect,
                "image_url": image_url,
                "action": action,
                "discord_message_id": discord_message_id,
                "workflow_id": workflow_id,
                "source": source,
                "user_id": user_id,
            },
        )

        if parent_turn_id:
            age.execute_write(
                """
                MATCH (child:ImageTurn {turn_id: $turn_id})
                MATCH (parent:ImageTurn {turn_id: $parent_turn_id})
                MERGE (child)-[d:DERIVED_FROM]->(parent)
                SET d.strength = $strength
                RETURN d
                """,
                {
                    "turn_id": turn_id,
                    "parent_turn_id": parent_turn_id,
                    "strength": strength,
                },
            )

        for ref_url in reference_urls or []:
            age.execute_write(
                """
                MATCH (t:ImageTurn {turn_id: $turn_id})
                MERGE (img:RefImage {url: $ref_url})
                MERGE (t)-[:REFERENCES]->(img)
                RETURN img.url
                """,
                {"turn_id": turn_id, "ref_url": ref_url},
            )
        if user_id:
            age.execute_write(
                """
                MATCH (t:ImageTurn {turn_id: $turn_id})
                MERGE (u:PortalUser {user_id: $user_id})
                MERGE (t)-[:CREATED_BY]->(u)
                RETURN u.user_id
                """,
                {"turn_id": turn_id, "user_id": user_id},
            )
        return True
    except Exception as exc:  # noqa: BLE001 - persistence must never break a job
        logger.warning("image_turn_persist_failed", error=str(exc), turn_id=turn_id)
        return False


def update_turn_rating(turn_id: str, rating: int, *, graph_name: str = _GRAPH) -> bool:
    """Set ``user_rating`` on an existing ImageTurn node. Returns success."""
    try:
        age = get_age(graph_name=graph_name)
        age.execute_write(
            """
            MATCH (t:ImageTurn {turn_id: $turn_id})
            SET t.user_rating = $rating
            RETURN t.turn_id
            """,
            {"turn_id": turn_id, "rating": rating},
        )
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_turn_rating_failed", error=str(exc), turn_id=turn_id)
        return False


def list_turns_for_user(
    user_id: str,
    *,
    limit: int = 24,
    offset: int = 0,
    graph_name: str = _GRAPH,
) -> list[dict[str, Any]]:
    """Return ImageTurn nodes owned by a portal user."""
    try:
        age = get_age(graph_name=graph_name)
        rows = age.execute_cypher(
            """
            MATCH (t:ImageTurn)
            WHERE t.user_id = $user_id
            RETURN t.turn_id AS turn_id, t.provider AS provider, t.model AS model,
                   t.prompt_raw AS prompt_raw, t.image_url AS image_url,
                   t.action AS action, t.workflow_id AS workflow_id,
                   t.user_rating AS user_rating, t.aspect AS aspect
            ORDER BY t.turn_id DESC
            SKIP $offset LIMIT $limit
            """,
            {"user_id": user_id, "limit": limit, "offset": offset},
        )
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_turn_list_user_failed", error=str(exc), user_id=user_id)
        return []


def list_recent_turns(
    *,
    limit: int = 24,
    offset: int = 0,
    provider: Optional[str] = None,
    workflow_id: Optional[str] = None,
    graph_name: str = _GRAPH,
) -> list[dict[str, Any]]:
    """Return recent ImageTurn nodes for gallery views."""
    try:
        age = get_age(graph_name=graph_name)
        where_clauses = []
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if provider:
            where_clauses.append("t.provider = $provider")
            params["provider"] = provider
        if workflow_id:
            where_clauses.append("t.workflow_id = $workflow_id")
            params["workflow_id"] = workflow_id
        where = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""
        rows = age.execute_cypher(
            f"""
            MATCH (t:ImageTurn)
            {where}
            RETURN t.turn_id AS turn_id, t.provider AS provider, t.model AS model,
                   t.prompt_raw AS prompt_raw, t.image_url AS image_url,
                   t.action AS action, t.workflow_id AS workflow_id,
                   t.user_rating AS user_rating, t.aspect AS aspect
            ORDER BY t.turn_id DESC
            SKIP $offset LIMIT $limit
            """,
            params,
        )
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_turn_list_failed", error=str(exc))
        return []


def get_turn(turn_id: str, *, graph_name: str = _GRAPH) -> Optional[dict[str, Any]]:
    try:
        age = get_age(graph_name=graph_name)
        rows = age.execute_cypher(
            """
            MATCH (t:ImageTurn {turn_id: $turn_id})
            RETURN t.turn_id AS turn_id, t.provider AS provider, t.model AS model,
                   t.prompt_raw AS prompt_raw, t.prompt_expanded AS prompt_expanded,
                   t.image_url AS image_url, t.action AS action,
                   t.workflow_id AS workflow_id, t.user_rating AS user_rating,
                   t.aspect AS aspect, t.discord_message_id AS discord_message_id
            """,
            {"turn_id": turn_id},
        )
        return dict(rows[0]) if rows else None
    except Exception as exc:  # noqa: BLE001
        logger.warning("image_turn_get_failed", error=str(exc), turn_id=turn_id)
        return None
