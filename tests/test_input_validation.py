"""Input-hardening tests: bounds on untrusted structure and free text.

These cover the engine guards that keep a malformed or hostile request from
creating an unplayable game (bad player count, duplicate/blank IDs) or from
amplifying memory and bandwidth through oversized chat and names. Chat, names,
and rosters all reach the engine from remote, token-authenticated clients, so
the engine is the enforcement point.
"""

import asyncio

import pytest
from helpers import ROLES_5, ROLES_7, make_engine

from avalon.game import (
    MAX_CHAT_LENGTH,
    MAX_NAME_LENGTH,
    MAX_PLAYERS,
    MIN_PLAYERS,
    GameEngine,
)
from avalon.models import CreateGameRequest, Player


def _players(count, *, bots=False):
    return [Player(id=f"p{i + 1}", name=f"P{i + 1}", is_bot=bots) for i in range(count)]


async def _started(engine: GameEngine, roles):
    await engine.create_game(CreateGameRequest(players=_players(len(roles)), roles=list(roles)))
    await engine.start_game()
    return engine


# --- create_game structural guards ---------------------------------------


def test_create_game_rejects_too_few_players_even_with_roles():
    # A four-player roster with four roles would slip past the role-count check,
    # then crash at propose time because QUEST_TEAM_SIZES has no 4-player row.
    async def scenario():
        with pytest.raises(ValueError, match="不支持的玩家数量"):
            await make_engine().create_game(
                CreateGameRequest(players=_players(4), roles=ROLES_5[:4])
            )

    asyncio.run(scenario())


def test_create_game_rejects_too_many_players():
    async def scenario():
        roles = list(ROLES_7) + [r for r in ROLES_5[:4]]  # 11 roles
        with pytest.raises(ValueError, match="不支持的玩家数量"):
            await make_engine().create_game(
                CreateGameRequest(players=_players(11), roles=roles)
            )

    asyncio.run(scenario())


def test_create_game_rejects_duplicate_player_ids():
    async def scenario():
        roster = _players(5)
        roster[1].id = roster[0].id  # collide two seats on one id
        with pytest.raises(ValueError, match="不能重复"):
            await make_engine().create_game(CreateGameRequest(players=roster, roles=ROLES_5))

    asyncio.run(scenario())


def test_create_game_rejects_empty_player_ids():
    async def scenario():
        roster = _players(5)
        roster[0].id = ""
        with pytest.raises(ValueError, match="不能为空"):
            await make_engine().create_game(CreateGameRequest(players=roster, roles=ROLES_5))

    asyncio.run(scenario())


def test_create_game_accepts_the_supported_range():
    async def scenario():
        for count in range(MIN_PLAYERS, MAX_PLAYERS + 1):
            state = await make_engine().create_game(CreateGameRequest(players=_players(count)))
            assert state.config.player_count == count

    asyncio.run(scenario())


# --- chat length guard ----------------------------------------------------


def test_chat_rejects_blank_and_whitespace_only_messages():
    async def scenario():
        engine = await _started(make_engine(), ROLES_5)
        with pytest.raises(ValueError, match="消息不能为空"):
            await engine.apply_action("p1", "chat", {"message": ""})
        with pytest.raises(ValueError, match="消息不能为空"):
            await engine.apply_action("p1", "chat", {"message": "   "})
        assert engine.state.chat == []

    asyncio.run(scenario())


def test_chat_rejects_oversized_messages_but_allows_the_limit():
    async def scenario():
        engine = await _started(make_engine(), ROLES_5)
        with pytest.raises(ValueError, match="消息过长"):
            await engine.apply_action("p1", "chat", {"message": "x" * (MAX_CHAT_LENGTH + 1)})
        assert engine.state.chat == []
        # Exactly at the cap is fine.
        await engine.apply_action("p1", "chat", {"message": "x" * MAX_CHAT_LENGTH})
        assert len(engine.state.chat) == 1

    asyncio.run(scenario())


def test_chat_rejects_non_string_payloads():
    async def scenario():
        engine = await _started(make_engine(), ROLES_5)
        with pytest.raises(ValueError, match="消息不能为空"):
            await engine.apply_action("p1", "chat", {"message": {"nested": "obj"}})

    asyncio.run(scenario())


# --- name length guard ----------------------------------------------------


def test_rename_rejects_oversized_names_and_trims_whitespace():
    async def scenario():
        engine = make_engine()
        await engine.create_game(CreateGameRequest(players=_players(5), roles=ROLES_5))
        with pytest.raises(ValueError, match="名字过长"):
            await engine.rename_player("p1", "z" * (MAX_NAME_LENGTH + 1))
        with pytest.raises(ValueError, match="名字不能为空"):
            await engine.rename_player("p1", "   ")
        await engine.rename_player("p1", "  Alice  ")
        assert engine.state.players[0].name == "Alice"

    asyncio.run(scenario())


def test_add_player_rejects_oversized_names():
    async def scenario():
        engine = make_engine()
        await engine.create_game(CreateGameRequest(players=_players(5), roles=ROLES_5))
        with pytest.raises(ValueError, match="名字过长"):
            await engine.add_player(is_bot=True, name="b" * (MAX_NAME_LENGTH + 1))
        # A blank explicit name falls back to the generated default.
        state = await engine.add_player(is_bot=True, name=None)
        assert state.players[-1].name.startswith("机器人")

    asyncio.run(scenario())
