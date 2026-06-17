"""Shared builders for engine-level tests.

These bypass start_game's random shuffle so each test controls exactly which
player holds which role and who leads first.
"""

from __future__ import annotations

from typing import Optional, Sequence

from avalon.game import GameEngine
from avalon.models import CreateGameRequest, Phase, Player, Role
from avalon.storage import EventStore

ROLES_5 = [Role.merlin, Role.percival, Role.loyal_servant, Role.assassin, Role.minion]
ROLES_6 = [
    Role.merlin,
    Role.percival,
    Role.loyal_servant,
    Role.loyal_servant,
    Role.assassin,
    Role.morgana,
]
ROLES_7 = [
    Role.merlin,
    Role.percival,
    Role.loyal_servant,
    Role.loyal_servant,
    Role.assassin,
    Role.morgana,
    Role.minion,
]


def make_engine() -> GameEngine:
    return GameEngine(EventStore(":memory:"))


async def started_engine(
    roles: Sequence[Role],
    *,
    bots: Optional[Sequence[bool]] = None,
    names: Optional[Sequence[str]] = None,
    hammer_auto_approve: bool = True,
    lady_of_lake: bool = False,
) -> GameEngine:
    """Engine with a started game where players p1..pN hold `roles` in order."""
    count = len(roles)
    bot_flags = list(bots) if bots is not None else [False] * count
    player_names = list(names) if names is not None else [f"P{i + 1}" for i in range(count)]
    players = [
        Player(id=f"p{i + 1}", name=player_names[i], is_bot=bot_flags[i]) for i in range(count)
    ]
    engine = make_engine()
    await engine.create_game(
        CreateGameRequest(
            players=players,
            roles=list(roles),
            hammer_auto_approve=hammer_auto_approve,
            lady_of_lake=lady_of_lake,
        )
    )
    state = engine.state
    for player, role in zip(state.players, roles):
        player.role = role
    state.started = True
    state.phase = Phase.team_proposal
    state.leader_index = 0
    state.quest_number = 1
    state.proposal_attempts = 0
    # Mirror start_game's Lady-of-the-Lake setup so the holder is real.
    state.lady_holder_id = state.players[0].id if lady_of_lake else None
    state.lady_last_used_quest = None
    state.lady_history = []
    return engine


def leader_id(engine: GameEngine) -> str:
    state = engine.state
    return state.players[state.leader_index].id


async def propose(engine: GameEngine, team: Sequence[str]) -> None:
    await engine.apply_action(leader_id(engine), "propose_team", {"team": list(team)})


async def vote_team(engine: GameEngine, approvals: dict[str, bool]) -> None:
    for pid, approve in approvals.items():
        await engine.apply_action(pid, "vote_team", {"approve": approve})


async def run_quest(engine: GameEngine, votes: dict[str, bool]) -> None:
    for pid, success in votes.items():
        await engine.apply_action(pid, "quest_vote", {"success": success})


def event_types(engine: GameEngine) -> list[str]:
    return [event.type for event in engine._store.list_events()]
