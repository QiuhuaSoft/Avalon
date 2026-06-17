"""Parsing-layer tests: turning raw LLM text into structured actions.

These pure helpers ( ``LLMClient.extract_*`` and ``BotPolicy._resolve_name_to_id`` )
sit between the model and the rules engine. They never load a model, so the
suite exercises them directly with the kinds of replies a real LLM produces:
extra prose, wrong casing, quoted messages, and leaked action keywords.
"""

from __future__ import annotations

import pytest
from helpers import started_engine

from avalon.bot.llm import LLMClient
from avalon.bot.policy import BotPolicy
from avalon.models import GameConfig, GameState, Phase, Player, Role

# --- TEAM: --------------------------------------------------------------

def test_extract_team_parses_comma_separated_names():
    result = LLMClient.extract_team("SAY: let's try this.\nTEAM: Alice, Bob, Carol")
    assert result.success
    assert result.value == ["Alice", "Bob", "Carol"]


def test_extract_team_is_case_insensitive_and_trims_whitespace():
    result = LLMClient.extract_team("team:   Alice ,Bob  ")
    assert result.success
    assert result.value == ["Alice", "Bob"]


def test_extract_team_ignores_empty_entries_from_trailing_commas():
    result = LLMClient.extract_team("TEAM: Alice, , Bob,")
    assert result.success
    assert result.value == ["Alice", "Bob"]


def test_extract_team_stops_at_newline():
    # A SAY line below the team must not be swallowed into the roster.
    result = LLMClient.extract_team("TEAM: Alice, Bob\nSAY: trailing chatter")
    assert result.success
    assert result.value == ["Alice", "Bob"]


def test_extract_team_reports_missing_line():
    result = LLMClient.extract_team("I think we should send Alice and Bob.")
    assert not result.success
    assert "TEAM" in result.error


def test_extract_team_reports_empty_line():
    result = LLMClient.extract_team("TEAM: \nSAY: hi")
    assert not result.success


def test_extract_team_does_not_capture_the_following_line():
    # Regression: an empty TEAM line used to swallow the next line (here the
    # SAY line) because the separator matched the newline.
    result = LLMClient.extract_team("TEAM:\nSAY: oops this is chat")
    assert not result.success
    assert result.value != ["SAY: oops this is chat"]


# --- VOTE: --------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("VOTE: APPROVE", True),
        ("VOTE: REJECT", False),
        ("vote: approve", True),
        ("blah blah\nVOTE:   reject  \nmore", False),
    ],
)
def test_extract_vote(text, expected):
    result = LLMClient.extract_vote(text)
    assert result.success
    assert result.value is expected


def test_extract_vote_requires_a_recognized_keyword():
    result = LLMClient.extract_vote("VOTE: maybe")
    assert not result.success


# --- QUEST: -------------------------------------------------------------

@pytest.mark.parametrize(
    "text,expected",
    [
        ("QUEST: SUCCESS", True),
        ("QUEST: FAIL", False),
        ("quest: success", True),
    ],
)
def test_extract_quest(text, expected):
    result = LLMClient.extract_quest(text)
    assert result.success
    assert result.value is expected


def test_extract_quest_rejects_unknown_value():
    assert not LLMClient.extract_quest("QUEST: sabotage").success


# --- SAY: ---------------------------------------------------------------

def test_extract_say_returns_the_message():
    result = LLMClient.extract_say("SAY: nothing to go on yet\nVOTE: APPROVE")
    assert result.success
    assert result.value == "nothing to go on yet"


def test_extract_say_strips_matched_quotes():
    assert LLMClient.extract_say('SAY: "hello there"').value == "hello there"
    assert LLMClient.extract_say("SAY: 'hello there'").value == "hello there"


def test_extract_say_strips_leaked_action_keyword_on_the_same_line():
    # Models sometimes append the action to the SAY line; it must not leak to chat.
    result = LLMClient.extract_say("SAY: I approve this team VOTE: APPROVE")
    assert result.success
    assert result.value == "I approve this team"
    assert "APPROVE" not in result.value


def test_extract_say_rejects_a_line_that_is_only_a_leaked_keyword():
    result = LLMClient.extract_say("SAY: TARGET: Alice")
    assert not result.success


def test_extract_say_reports_missing_line():
    assert not LLMClient.extract_say("VOTE: APPROVE").success


def test_extract_say_does_not_capture_the_following_line():
    # Regression: an empty SAY line must not pull the next line into chat.
    result = LLMClient.extract_say("SAY:\nThis prose belongs to no field.")
    assert not result.success


# --- TARGET: / INSPECT: -------------------------------------------------

def test_extract_target_default_keyword():
    result = LLMClient.extract_target("TARGET: Alice")
    assert result.success
    assert result.value == "Alice"


def test_extract_target_custom_keyword():
    result = LLMClient.extract_target("INSPECT: Bob", keyword="INSPECT")
    assert result.success
    assert result.value == "Bob"


def test_extract_target_wrong_keyword_fails():
    # An INSPECT reply must not satisfy a TARGET extraction.
    assert not LLMClient.extract_target("INSPECT: Bob", keyword="TARGET").success


def test_extract_target_does_not_capture_the_following_line():
    # Regression: an empty TARGET line previously captured the trailing SAY
    # line as the target name (e.g. "SAY: foo").
    result = LLMClient.extract_target("TARGET:\nSAY: I think it is Merlin")
    assert not result.success


# --- name resolution ----------------------------------------------------

def _resolver_state() -> GameState:
    players = [
        Player(id="p1", name="Alice", role=Role.merlin),
        Player(id="p2", name="Bob", role=Role.percival),
        Player(id="p3", name="Carol", role=Role.assassin),
    ]
    config = GameConfig(player_count=3, roles=[p.role for p in players])
    return GameState(id="g", config=config, players=players, started=True, phase=Phase.team_vote)


def test_resolve_name_exact_case_insensitive():
    policy = BotPolicy()
    state = _resolver_state()
    assert policy._resolve_name_to_id(state, "alice") == "p1"
    assert policy._resolve_name_to_id(state, "  BOB  ") == "p2"


def test_resolve_name_partial_match():
    policy = BotPolicy()
    state = _resolver_state()
    # "Car" is a substring of "Carol".
    assert policy._resolve_name_to_id(state, "Car") == "p3"


def test_resolve_name_unknown_returns_none():
    policy = BotPolicy()
    state = _resolver_state()
    assert policy._resolve_name_to_id(state, "Zelda") is None


def test_resolve_name_prefers_exact_over_partial():
    # With names that are prefixes of one another, an exact request must win
    # regardless of player ordering.
    players = [
        Player(id="p1", name="Ann", role=Role.merlin),
        Player(id="p2", name="Anna", role=Role.assassin),
    ]
    config = GameConfig(player_count=2, roles=[p.role for p in players])
    state = GameState(id="g", config=config, players=players, started=True)
    policy = BotPolicy()
    assert policy._resolve_name_to_id(state, "Anna") == "p2"
    assert policy._resolve_name_to_id(state, "Ann") == "p1"


def test_resolved_names_round_trip_against_real_roster():
    # Guard against drift between the resolver and the engine's own roster.
    import asyncio

    async def scenario():
        engine = await started_engine(
            [Role.merlin, Role.percival, Role.loyal_servant, Role.assassin, Role.minion],
            names=["Alice", "Bob", "Carol", "Dave", "Eve"],
        )
        policy = BotPolicy()
        state = engine.state
        for player in state.players:
            assert policy._resolve_name_to_id(state, player.name) == player.id

    asyncio.run(scenario())
