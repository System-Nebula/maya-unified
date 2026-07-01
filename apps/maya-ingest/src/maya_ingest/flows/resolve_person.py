"""Run cross-platform entity resolution for a single channel.

Compares the channel against every other known channel; auto-links above
the resolver's threshold, otherwise records a person_channel suggestion row
with the signal breakdown.
"""

from __future__ import annotations

from maya_db import (
    Channel as ChannelDB,
    Person as PersonDB,
    PersonChannel as PersonChannelDB,
    get_async_session,
)
from maya_graph import PersonResolver, ResolverInput
from prefect import flow, get_run_logger
from sqlalchemy import select


@flow(name="resolve-person-for-channel")
async def resolve_person_for_channel(channel_id: str) -> dict:
    logger = get_run_logger()
    resolver = PersonResolver()
    decisions = {"auto_link": 0, "suggest": 0, "ignore": 0}

    async for session in get_async_session():
        target = await session.get(ChannelDB, channel_id)
        if target is None:
            return decisions
        target_input = _to_input(target)

        others = (
            await session.execute(
                select(ChannelDB).where(ChannelDB.id != target.id)
            )
        ).scalars().all()

        for other in others:
            confidence, signals = resolver.score(target_input, _to_input(other))
            decision = resolver.decide(confidence)
            decisions[decision] += 1
            if decision == "ignore":
                continue
            existing = (
                await session.execute(
                    select(PersonChannelDB).where(PersonChannelDB.channel_id == target.id)
                )
            ).scalar_one_or_none()
            if existing:
                person_id = existing.person_id
            else:
                person = PersonDB(
                    display_name=target.display_name,
                    identity_confidence=confidence,
                )
                session.add(person)
                await session.flush()
                person_id = person.id
                session.add(
                    PersonChannelDB(
                        person_id=person_id,
                        channel_id=target.id,
                        confidence=1.0,
                        signals=[],
                    )
                )
            session.add(
                PersonChannelDB(
                    person_id=person_id,
                    channel_id=other.id,
                    confidence=confidence,
                    signals=[s.model_dump() for s in signals],
                )
            )
        await session.commit()
    logger.info("resolved %s decisions=%s", channel_id, decisions)
    return decisions


def _to_input(c: ChannelDB) -> ResolverInput:
    return ResolverInput(
        channel_id=str(c.id),
        platform=c.platform,
        handle=c.handle,
        display_name=c.display_name,
        bio=c.description,
        profile_links=list(c.profile_links or []),
    )
