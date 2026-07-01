"""
Cross-modal arena service.

Supports explicit votes and lower-weight passive reaction signals across
multiple modalities.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy.exc import SQLAlchemyError

from opentelemetry import trace

from arena_core.elo import ELOCalculator
from maya_db.models.arena import (
    ArenaArtifact,
    ArenaBattle,
    ArenaCandidate,
    ArenaSession,
    ArenaVote,
)
from maya_db.sync_connection import get_sync_connection

logger = structlog.get_logger()
_tracer = trace.get_tracer("lib.arena.service")

SENTIMENT_ANCHOR_RATING = 1200

REACTION_CHOICE_MAP = {
    "🅰️": "a",
    "🇦": "a",
    "a": "a",
    "A": "a",
    "🅱️": "b",
    "🇧": "b",
    "b": "b",
    "B": "b",
    "🤝": "tie",
    "⚖️": "tie",
    "tie": "tie",
}

SENTIMENT_DIRECTION_MAP = {
    "👍": "up",
    "⬆️": "up",
    "⬆": "up",
    "+1": "up",
    "up": "up",
    "👎": "down",
    "⬇️": "down",
    "⬇": "down",
    "-1": "down",
    "down": "down",
}

PASSIVE_SIGNAL_WEIGHT = 0.35


@dataclass
class WeightedTally:
    choice: str
    total: float


class ArenaService:
    """Generic ranking and battle orchestration for multiple modalities."""

    def __init__(self):
        self._db = None
        self._candidate_cache: dict[str, ArenaCandidate] = {}
        self._battle_cache: dict[str, ArenaBattle] = {}
        self._artifact_cache: list[ArenaArtifact] = []
        self._vote_cache: list[ArenaVote] = []
        self._session_cache: dict[str, ArenaSession] = {}
        self._battle_by_message: dict[str, str] = {}

    def _get_db(self):
        if self._db is None:
            self._db = get_sync_connection()
        return self._db

    def _session(self):
        return self._get_db().get_session()

    def _store_candidate(self, candidate: ArenaCandidate) -> ArenaCandidate:
        self._candidate_cache[candidate.id] = candidate
        return candidate

    def _store_battle(self, battle: ArenaBattle) -> ArenaBattle:
        self._battle_cache[battle.id] = battle
        return battle

    def _store_artifact(self, artifact: ArenaArtifact) -> ArenaArtifact:
        self._artifact_cache.append(artifact)
        return artifact

    def _store_vote(self, vote: ArenaVote) -> ArenaVote:
        self._vote_cache.append(vote)
        return vote

    def _store_session(self, arena_session: ArenaSession) -> ArenaSession:
        self._session_cache[arena_session.id] = arena_session
        if arena_session.message_id:
            self._battle_by_message[arena_session.message_id] = arena_session.battle_id
        return arena_session

    def _get_cached_session_for_battle(self, battle_id: str) -> Optional[ArenaSession]:
        for arena_session in self._session_cache.values():
            if arena_session.battle_id == battle_id:
                return arena_session
        return None

    def add_candidate(
        self,
        name: str,
        provider: str,
        model_key: Optional[str] = None,
        description: str | None = None,
        settings: Optional[dict] = None,
        *,
        voice_id: Optional[str] = None,
        modality: str = "tts",
        variant_key: Optional[str] = None,
    ) -> ArenaCandidate:
        """Add a new candidate. `voice_id` is kept as a legacy alias."""
        resolved_model_key = model_key or voice_id
        if not resolved_model_key:
            raise ValueError("model_key or voice_id is required")

        candidate = ArenaCandidate(
            id=str(uuid.uuid4()),
            name=name,
            modality=modality,
            provider=provider,
            model_key=resolved_model_key,
            variant_key=variant_key,
            description=description,
            config=settings or {},
            rating=1200,
            rating_deviation=350,
            wins=0,
            losses=0,
            draws=0,
            total_battles=0,
            is_active=True,
        )
        self._store_candidate(candidate)
        try:
            session = self._session()
            session.add(candidate)
            session.commit()
        except SQLAlchemyError as exc:
            logger.warning("arena_candidate_persistence_failed", error=str(exc), candidate_id=candidate.id)
        logger.info("arena_candidate_added", candidate_id=candidate.id, modality=modality, provider=provider)
        return candidate

    def ensure_candidate(
        self,
        *,
        modality: str,
        provider: str,
        model_key: str,
        display_name: str,
        variant_key: Optional[str] = None,
        config: Optional[dict] = None,
        description: Optional[str] = None,
    ) -> ArenaCandidate:
        try:
            session = self._session()
            candidate = (
                session.query(ArenaCandidate)
                .filter(ArenaCandidate.modality == modality)
                .filter(ArenaCandidate.provider == provider)
                .filter(ArenaCandidate.model_key == model_key)
                .filter(ArenaCandidate.variant_key == variant_key)
                .first()
            )
            if candidate:
                self._store_candidate(candidate)
                return candidate
        except SQLAlchemyError:
            candidate = next(
                (
                    cached
                    for cached in self._candidate_cache.values()
                    if cached.modality == modality
                    and cached.provider == provider
                    and cached.model_key == model_key
                    and cached.variant_key == variant_key
                ),
                None,
            )
            if candidate:
                return candidate
        return self.add_candidate(
            name=display_name,
            provider=provider,
            model_key=model_key,
            description=description,
            settings=config,
            modality=modality,
            variant_key=variant_key,
        )

    def get_candidate(self, candidate_id: str) -> Optional[ArenaCandidate]:
        try:
            session = self._session()
            candidate = session.query(ArenaCandidate).filter(ArenaCandidate.id == candidate_id).first()
            if candidate is not None:
                self._store_candidate(candidate)
                return candidate
            return self._candidate_cache.get(candidate_id)
        except SQLAlchemyError:
            return self._candidate_cache.get(candidate_id)

    def get_all_candidates(self, active_only: bool = True, modality: Optional[str] = None) -> list[ArenaCandidate]:
        try:
            session = self._session()
            query = session.query(ArenaCandidate)
            if active_only:
                query = query.filter(ArenaCandidate.is_active == True)
            if modality:
                query = query.filter(ArenaCandidate.modality == modality)
            rows = query.order_by(ArenaCandidate.rating.desc()).all()
            for row in rows:
                self._store_candidate(row)
            return rows
        except SQLAlchemyError:
            rows = list(self._candidate_cache.values())
            if active_only:
                rows = [c for c in rows if c.is_active]
            if modality:
                rows = [c for c in rows if c.modality == modality]
            return sorted(rows, key=lambda c: c.rating, reverse=True)

    def get_leaderboard(self, limit: int = 20, modality: Optional[str] = None) -> list[ArenaCandidate]:
        try:
            session = self._session()
            query = session.query(ArenaCandidate).filter(ArenaCandidate.is_active == True)
            if modality:
                query = query.filter(ArenaCandidate.modality == modality)
            rows = query.order_by(ArenaCandidate.rating.desc()).limit(limit).all()
            for row in rows:
                self._store_candidate(row)
            return rows
        except SQLAlchemyError:
            rows = list(self._candidate_cache.values())
            if modality:
                rows = [c for c in rows if c.modality == modality]
            rows = [c for c in rows if c.is_active]
            return sorted(rows, key=lambda c: c.rating, reverse=True)[:limit]

    def create_battle(
        self,
        candidate_a_id: str,
        candidate_b_id: str,
        prompt: str,
        prompt_source: Optional[str] = None,
        *,
        modality: Optional[str] = None,
        input_payload: Optional[dict] = None,
    ) -> ArenaBattle:
        candidate_a = self.get_candidate(candidate_a_id)
        candidate_b = self.get_candidate(candidate_b_id)
        if not candidate_a or not candidate_b:
            raise ValueError("One or both candidates not found")
        resolved_modality = modality or candidate_a.modality
        if candidate_a.modality != candidate_b.modality:
            raise ValueError("Candidates must share the same modality")

        with _tracer.start_as_current_span("arena.create_battle") as span:
            span.set_attribute("arena.modality", resolved_modality)
            battle = ArenaBattle(
                id=str(uuid.uuid4()),
                modality=resolved_modality,
                candidate_a_id=candidate_a_id,
                candidate_b_id=candidate_b_id,
                prompt=prompt,
                prompt_source=prompt_source,
                input_payload=input_payload or {},
                status="voting",
                votes_a=0,
                votes_b=0,
                votes_tie=0,
                total_votes=0,
                started_at=datetime.utcnow(),
            )
            span.set_attribute("arena.battle_id", battle.id)
            self._store_battle(battle)
            try:
                session = self._session()
                session.add(battle)
                session.commit()
            except SQLAlchemyError as exc:
                logger.warning("arena_battle_persistence_failed", error=str(exc), battle_id=battle.id)
            logger.info("arena_battle_created", battle_id=battle.id, modality=resolved_modality)
            return battle

    def add_artifact(
        self,
        *,
        battle_id: str,
        candidate_id: str,
        slot: str,
        artifact_type: str,
        url: Optional[str] = None,
        local_path: Optional[str] = None,
        mime_type: Optional[str] = None,
        metadata: Optional[dict] = None,
    ) -> ArenaArtifact:
        artifact = ArenaArtifact(
            id=str(uuid.uuid4()),
            battle_id=battle_id,
            candidate_id=candidate_id,
            slot=slot,
            artifact_type=artifact_type,
            url=url,
            local_path=local_path,
            mime_type=mime_type,
            extra_data=metadata or {},
        )
        self._store_artifact(artifact)
        try:
            session = self._session()
            session.add(artifact)
            session.commit()
        except SQLAlchemyError as exc:
            logger.warning("arena_artifact_persistence_failed", error=str(exc), battle_id=battle_id)
        return artifact

    def get_artifacts(self, battle_id: str) -> list[ArenaArtifact]:
        try:
            session = self._session()
            rows = (
                session.query(ArenaArtifact)
                .filter(ArenaArtifact.battle_id == battle_id)
                .order_by(ArenaArtifact.slot.asc(), ArenaArtifact.created_at.asc())
                .all()
            )
            if rows:
                self._artifact_cache.extend(rows)
            return rows
        except SQLAlchemyError:
            return [a for a in self._artifact_cache if a.battle_id == battle_id]

    def get_battle(self, battle_id: str) -> Optional[ArenaBattle]:
        try:
            session = self._session()
            battle = session.query(ArenaBattle).filter(ArenaBattle.id == battle_id).first()
            if battle is not None:
                self._store_battle(battle)
            return battle
        except SQLAlchemyError:
            return self._battle_cache.get(battle_id)

    def get_battle_by_message(self, message_id: str) -> Optional[ArenaBattle]:
        battle_id = self._battle_by_message.get(message_id)
        if battle_id:
            return self.get_battle(battle_id)
        try:
            session = self._session()
            mapped = session.query(ArenaSession).filter(ArenaSession.message_id == message_id).first()
            if not mapped:
                return self._get_battle_by_slot_message(message_id)
            self._store_session(mapped)
            return self.get_battle(mapped.battle_id)
        except SQLAlchemyError:
            return self._get_battle_by_slot_message(message_id)

    def resolve_sentiment_slot(self, battle: ArenaBattle, message_id: str) -> Optional[str]:
        payload = battle.input_payload or {}
        slot_messages = payload.get("slot_message_ids") or {}
        for slot, mid in slot_messages.items():
            if str(mid) == str(message_id):
                return slot
        session_row = self._get_cached_session_for_battle(battle.id)
        if session_row and session_row.message_id == message_id:
            return None
        return None

    def _get_battle_by_slot_message(self, message_id: str) -> Optional[ArenaBattle]:
        for battle in self._battle_cache.values():
            slot = self.resolve_sentiment_slot(battle, message_id)
            if slot is not None:
                return battle
        try:
            session = self._session()
            rows = session.query(ArenaBattle).filter(ArenaBattle.status == "voting").all()
            for battle in rows:
                self._store_battle(battle)
                if self.resolve_sentiment_slot(battle, message_id):
                    return battle
        except SQLAlchemyError:
            pass
        return None

    def get_battles(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
        modality: Optional[str] = None,
    ) -> list[ArenaBattle]:
        try:
            session = self._session()
            query = session.query(ArenaBattle)
            if status:
                query = query.filter(ArenaBattle.status == status)
            if modality:
                query = query.filter(ArenaBattle.modality == modality)
            rows = query.order_by(ArenaBattle.created_at.desc()).limit(limit).offset(offset).all()
            for row in rows:
                self._store_battle(row)
            return rows
        except SQLAlchemyError:
            rows = list(self._battle_cache.values())
            if status:
                rows = [b for b in rows if b.status == status]
            if modality:
                rows = [b for b in rows if b.modality == modality]
            rows.sort(key=lambda b: b.created_at or datetime.utcnow(), reverse=True)
            return rows[offset : offset + limit]

    def create_session(
        self,
        *,
        battle_id: str,
        started_by: str,
        channel_id: Optional[str] = None,
        guild_id: Optional[str] = None,
        message_id: Optional[str] = None,
    ) -> ArenaSession:
        arena_session = ArenaSession(
            id=str(uuid.uuid4()),
            battle_id=battle_id,
            started_by=started_by,
            channel_id=channel_id,
            guild_id=guild_id,
            message_id=message_id,
        )
        self._store_session(arena_session)
        try:
            session = self._session()
            session.add(arena_session)
            session.commit()
        except SQLAlchemyError as exc:
            logger.warning("arena_session_persistence_failed", error=str(exc), battle_id=battle_id)
        return arena_session

    def bind_message(self, battle_id: str, message_id: str) -> None:
        try:
            session = self._session()
            arena_session = session.query(ArenaSession).filter(ArenaSession.battle_id == battle_id).first()
            if arena_session is None:
                arena_session = ArenaSession(id=str(uuid.uuid4()), battle_id=battle_id, started_by="system")
                session.add(arena_session)
            arena_session.message_id = message_id
            session.commit()
            self._store_session(arena_session)
        except SQLAlchemyError as exc:
            logger.warning("arena_bind_message_failed", error=str(exc), battle_id=battle_id)
            arena_session = self._get_cached_session_for_battle(battle_id)
            if arena_session is None:
                arena_session = ArenaSession(id=str(uuid.uuid4()), battle_id=battle_id, started_by="system")
            arena_session.message_id = message_id
            self._store_session(arena_session)

    def _record_signal(
        self,
        *,
        battle_id: str,
        user_id: str,
        username: str,
        choice: str,
        signal_type: str,
        weight: float,
        reaction: Optional[str] = None,
    ) -> ArenaVote:
        session = None
        try:
            session = self._session()
            battle = session.query(ArenaBattle).filter(ArenaBattle.id == battle_id).first()
        except SQLAlchemyError:
            battle = self.get_battle(battle_id)
        if not battle:
            raise ValueError("Battle not found")
        if battle.status != "voting":
            raise ValueError("Battle is not open for voting")
        is_sentiment = signal_type.startswith("sentiment:")
        if is_sentiment:
            if choice not in ("up", "down"):
                raise ValueError("Sentiment choice must be 'up' or 'down'")
        elif choice not in ("a", "b", "tie"):
            raise ValueError("Choice must be 'a', 'b', or 'tie'")

        existing = None
        if session is not None:
            try:
                existing = (
                    session.query(ArenaVote)
                    .filter(ArenaVote.battle_id == battle_id)
                    .filter(ArenaVote.user_id == user_id)
                    .filter(ArenaVote.signal_type == signal_type)
                    .first()
                )
            except SQLAlchemyError:
                existing = next(
                    (
                        vote
                        for vote in self._vote_cache
                        if vote.battle_id == battle_id and vote.user_id == user_id and vote.signal_type == signal_type
                    ),
                    None,
                )
        else:
            existing = next(
                (
                    vote
                    for vote in self._vote_cache
                    if vote.battle_id == battle_id and vote.user_id == user_id and vote.signal_type == signal_type
                ),
                None,
            )
        if existing:
            raise ValueError(f"User already submitted {signal_type} for this battle")

        vote = ArenaVote(
            id=str(uuid.uuid4()),
            battle_id=battle_id,
            user_id=user_id,
            username=username,
            choice=choice,
            signal_type=signal_type,
            reaction=reaction,
            weight=weight,
        )
        if not is_sentiment:
            if choice == "a":
                battle.votes_a += weight
            elif choice == "b":
                battle.votes_b += weight
            else:
                battle.votes_tie += weight
            battle.total_votes += weight
        self._store_vote(vote)
        if session is not None:
            try:
                session.add(vote)
                session.commit()
            except SQLAlchemyError as exc:
                logger.warning("arena_vote_persistence_failed", error=str(exc), battle_id=battle_id)
        return vote

    def vote(self, battle_id: str, user_id: str, username: str, choice: str) -> ArenaVote:
        with _tracer.start_as_current_span("arena.vote") as span:
            span.set_attribute("arena.battle_id", battle_id)
            span.set_attribute("arena.choice", choice)
            return self._record_signal(
                battle_id=battle_id,
                user_id=user_id,
                username=username,
                choice=choice,
                signal_type="explicit_vote",
                weight=1.0,
            )

    def record_reaction_signal(
        self,
        *,
        battle_id: str,
        user_id: str,
        username: str,
        reaction: str,
        weight: float = PASSIVE_SIGNAL_WEIGHT,
    ) -> ArenaVote:
        mapped = REACTION_CHOICE_MAP.get(reaction)
        if mapped is None:
            raise ValueError(f"Unsupported reaction signal: {reaction}")
        return self._record_signal(
            battle_id=battle_id,
            user_id=user_id,
            username=username,
            choice=mapped,
            signal_type="reaction",
            weight=weight,
            reaction=reaction,
        )

    def record_reaction_by_message(
        self,
        *,
        message_id: str,
        user_id: str,
        username: str,
        reaction: str,
        weight: float = PASSIVE_SIGNAL_WEIGHT,
    ) -> ArenaVote:
        battle = self.get_battle_by_message(message_id)
        if battle is None:
            raise ValueError("No active battle bound to message")
        direction = SENTIMENT_DIRECTION_MAP.get(reaction)
        if direction:
            slot = self.resolve_sentiment_slot(battle, message_id)
            if slot:
                vote = self.record_sentiment(
                    battle.id,
                    slot,
                    user_id,
                    username,
                    direction,
                    reaction=reaction,
                    weight=weight,
                )
                self.apply_sentiment_elo(battle.id, slot, direction)
                return vote
        return self.record_reaction_signal(
            battle_id=battle.id,
            user_id=user_id,
            username=username,
            reaction=reaction,
            weight=weight,
        )

    def record_sentiment(
        self,
        battle_id: str,
        candidate_slot: str,
        user_id: str,
        username: str,
        direction: str,
        *,
        reaction: Optional[str] = None,
        weight: float = PASSIVE_SIGNAL_WEIGHT,
    ) -> ArenaVote:
        if direction not in ("up", "down"):
            raise ValueError("Sentiment direction must be 'up' or 'down'")
        with _tracer.start_as_current_span("arena.record_sentiment") as span:
            span.set_attribute("arena.battle_id", battle_id)
            span.set_attribute("arena.candidate_slot", candidate_slot)
            span.set_attribute("arena.sentiment", direction)
            return self._record_signal(
                battle_id=battle_id,
                user_id=user_id,
                username=username,
                choice=direction,
                signal_type=f"sentiment:{candidate_slot}",
                weight=weight,
                reaction=reaction,
            )

    def apply_sentiment_elo(self, battle_id: str, candidate_slot: str, direction: str) -> None:
        """Adjust candidate ELO from thumbs-up/down against a fixed anchor rating."""
        battle = self.get_battle(battle_id)
        if not battle:
            return
        payload = battle.input_payload or {}
        slot_map = payload.get("candidate_ids") or payload.get("slot_map") or {}
        candidate_id = slot_map.get(candidate_slot)
        if not candidate_id:
            if candidate_slot == "a":
                candidate_id = battle.candidate_a_id
            elif candidate_slot == "b":
                candidate_id = battle.candidate_b_id
            else:
                extra = payload.get("extra_candidates") or {}
                candidate_id = extra.get(candidate_slot)
        if not candidate_id:
            return
        candidate = self.get_candidate(candidate_id)
        if not candidate:
            return
        k = int(ELOCalculator.K_FACTOR * PASSIVE_SIGNAL_WEIGHT)
        if direction == "up":
            result = ELOCalculator.calculate(candidate.rating, SENTIMENT_ANCHOR_RATING, k_factor=k)
            new_rating = result.winner_new_rating
        else:
            result = ELOCalculator.calculate(SENTIMENT_ANCHOR_RATING, candidate.rating, k_factor=k)
            new_rating = result.loser_new_rating
        candidate.rating = new_rating
        self._store_candidate(candidate)
        try:
            session = self._session()
            row = session.query(ArenaCandidate).filter(ArenaCandidate.id == candidate_id).first()
            if row:
                row.rating = new_rating
                session.commit()
        except SQLAlchemyError as exc:
            logger.warning("arena_sentiment_rating_persist_failed", error=str(exc), candidate_id=candidate_id)
        logger.info(
            "arena_sentiment_elo_applied",
            battle_id=battle_id,
            candidate_slot=candidate_slot,
            candidate_id=candidate_id,
            direction=direction,
            new_rating=new_rating,
        )

    def bind_slot_message(self, battle_id: str, candidate_slot: str, message_id: str) -> None:
        battle = self.get_battle(battle_id)
        if not battle:
            return
        payload = dict(battle.input_payload or {})
        slot_messages = dict(payload.get("slot_message_ids") or {})
        slot_messages[candidate_slot] = message_id
        payload["slot_message_ids"] = slot_messages
        battle.input_payload = payload
        self._store_battle(battle)
        self._battle_by_message[str(message_id)] = battle_id
        try:
            session = self._session()
            row = session.query(ArenaBattle).filter(ArenaBattle.id == battle_id).first()
            if row:
                row.input_payload = payload
                session.commit()
        except SQLAlchemyError as exc:
            logger.warning("arena_bind_slot_message_failed", error=str(exc), battle_id=battle_id)

    def forfeit_battle(self, battle_id: str, forfeiting_candidate_id: str, reason: str) -> ArenaBattle:
        with _tracer.start_as_current_span("arena.forfeit_battle") as span:
            span.set_attribute("arena.battle_id", battle_id)
            try:
                session = self._session()
                battle = session.query(ArenaBattle).filter(ArenaBattle.id == battle_id).first()
            except SQLAlchemyError:
                battle = self._battle_cache.get(battle_id)
                session = None
            if not battle:
                raise ValueError("Battle not found")
            span.set_attribute("arena.modality", battle.modality)
            if battle.status != "voting":
                raise ValueError(f"Battle is already {battle.status!r}, cannot forfeit")

            if forfeiting_candidate_id == battle.candidate_a_id:
                winner_id = battle.candidate_b_id
            elif forfeiting_candidate_id == battle.candidate_b_id:
                winner_id = battle.candidate_a_id
            else:
                raise ValueError("forfeiting_candidate_id is not part of this battle")

            if session is not None:
                winner = session.query(ArenaCandidate).filter(ArenaCandidate.id == winner_id).first()
                loser = session.query(ArenaCandidate).filter(ArenaCandidate.id == forfeiting_candidate_id).first()
            else:
                winner = self._candidate_cache.get(winner_id)
                loser = self._candidate_cache.get(forfeiting_candidate_id)
            if not winner or not loser:
                raise ValueError("Battle candidates missing")

            result = ELOCalculator.calculate(winner.rating, loser.rating)
            winner.rating = result.winner_new_rating
            loser.rating = result.loser_new_rating
            winner.wins += 1
            loser.losses += 1
            winner.total_battles += 1
            loser.total_battles += 1

            battle.winner_id = winner_id
            battle.status = "completed"
            battle.completed_at = datetime.utcnow()
            extra = dict(battle.extra_data or {})
            extra["forfeit_reason"] = reason
            battle.extra_data = extra

            if session is not None:
                try:
                    session.commit()
                except SQLAlchemyError as exc:
                    logger.warning("arena_forfeit_persistence_failed", error=str(exc), battle_id=battle_id)
            logger.warning(
                "arena_battle_forfeited",
                battle_id=battle_id,
                forfeiting_candidate_id=forfeiting_candidate_id,
                winner_id=winner_id,
                reason=reason,
                rating_change=result.loser_change,
            )
            return battle

    def complete_battle(self, battle_id: str) -> ArenaBattle:
        with _tracer.start_as_current_span("arena.complete_battle") as span:
            span.set_attribute("arena.battle_id", battle_id)
            try:
                session = self._session()
                battle = session.query(ArenaBattle).filter(ArenaBattle.id == battle_id).first()
            except SQLAlchemyError:
                battle = self._battle_cache.get(battle_id)
                session = None
            if not battle:
                raise ValueError("Battle not found")
            span.set_attribute("arena.modality", battle.modality)
            if battle.total_votes == 0:
                raise ValueError("Cannot complete battle with no votes")

            if battle.votes_a > battle.votes_b and battle.votes_a > battle.votes_tie:
                winner_id = battle.candidate_a_id
            elif battle.votes_b > battle.votes_a and battle.votes_b > battle.votes_tie:
                winner_id = battle.candidate_b_id
            else:
                winner_id = None

            if session is not None:
                candidate_a = session.query(ArenaCandidate).filter(ArenaCandidate.id == battle.candidate_a_id).first()
                candidate_b = session.query(ArenaCandidate).filter(ArenaCandidate.id == battle.candidate_b_id).first()
            else:
                candidate_a = self._candidate_cache.get(battle.candidate_a_id)
                candidate_b = self._candidate_cache.get(battle.candidate_b_id)
            if not candidate_a or not candidate_b:
                raise ValueError("Battle candidates missing")

            battle.winner_id = winner_id
            battle.status = "completed"
            battle.completed_at = datetime.utcnow()

            if winner_id is None:
                result = ELOCalculator.calculate(candidate_a.rating, candidate_b.rating, draw=True)
                candidate_a.rating = result.winner_new_rating
                candidate_b.rating = result.loser_new_rating
                candidate_a.draws += 1
                candidate_b.draws += 1
            elif winner_id == battle.candidate_a_id:
                result = ELOCalculator.calculate(candidate_a.rating, candidate_b.rating)
                candidate_a.rating = result.winner_new_rating
                candidate_b.rating = result.loser_new_rating
                candidate_a.wins += 1
                candidate_b.losses += 1
            else:
                result = ELOCalculator.calculate(candidate_b.rating, candidate_a.rating)
                candidate_b.rating = result.winner_new_rating
                candidate_a.rating = result.loser_new_rating
                candidate_b.wins += 1
                candidate_a.losses += 1

            candidate_a.total_battles += 1
            candidate_b.total_battles += 1
            if session is not None:
                try:
                    session.commit()
                except SQLAlchemyError as exc:
                    logger.warning("arena_complete_persistence_failed", error=str(exc), battle_id=battle_id)
            logger.info("arena_battle_completed", battle_id=battle_id, winner=winner_id)
            return battle

    def get_stats(self, modality: Optional[str] = None) -> dict:
        try:
            session = self._session()
            candidate_query = session.query(ArenaCandidate).filter(ArenaCandidate.is_active == True)
            battle_query = session.query(ArenaBattle)
            vote_query = session.query(ArenaVote)
            if modality:
                candidate_query = candidate_query.filter(ArenaCandidate.modality == modality)
                battle_query = battle_query.filter(ArenaBattle.modality == modality)
                vote_query = vote_query.join(ArenaBattle, ArenaVote.battle_id == ArenaBattle.id).filter(
                    ArenaBattle.modality == modality
                )
            total_battles = battle_query.count()
            completed_battles = battle_query.filter(ArenaBattle.status == "completed").count()
            return {
                "total_candidates": candidate_query.count(),
                "total_battles": total_battles,
                "completed_battles": completed_battles,
                "total_votes": vote_query.count(),
                "active_battles": battle_query.filter(ArenaBattle.status == "voting").count(),
            }
        except SQLAlchemyError:
            candidates = list(self._candidate_cache.values())
            battles = list(self._battle_cache.values())
            votes = list(self._vote_cache)
            if modality:
                candidates = [c for c in candidates if c.modality == modality]
                battles = [b for b in battles if b.modality == modality]
                filtered_votes = []
                for vote in votes:
                    vote_battle = self._battle_cache.get(vote.battle_id) or self.get_battle(vote.battle_id)
                    if vote_battle is not None and vote_battle.modality == modality:
                        filtered_votes.append(vote)
                votes = filtered_votes
            return {
                "total_candidates": len([c for c in candidates if c.is_active]),
                "total_battles": len(battles),
                "completed_battles": len([b for b in battles if b.status == "completed"]),
                "total_votes": len(votes),
                "active_battles": len([b for b in battles if b.status == "voting"]),
            }


_service: Optional[ArenaService] = None


def get_arena_service() -> ArenaService:
    global _service
    if _service is None:
        _service = ArenaService()
    return _service
