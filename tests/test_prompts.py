"""Prompt-builder tests: the text handed to the LLM for each role and phase.

These never invoke a model; they assert the structural invariants the parsing
layer and the rules engine depend on (correct task per phase, no secret-team
target leakage, stable action keywords).
"""

from __future__ import annotations

import random

import pytest

from avalon.bot.prompts import (
    build_action_instructions,
    build_context,
    build_system_prompt,
)
from avalon.models import GameConfig, GameState, Phase, Player, Role

ALL_ROLES = [
    Role.merlin,
    Role.percival,
    Role.loyal_servant,
    Role.assassin,
    Role.morgana,
    Role.mordred,
    Role.oberon,
    Role.minion,
]


def make_state(players, phase=Phase.team_proposal, **overrides):
    config = GameConfig(
        player_count=len(players),
        roles=[p.role for p in players],
        hammer_auto_approve=True,
        lady_of_lake=overrides.pop("lady_of_lake", False),
    )
    return GameState(
        id="g",
        config=config,
        players=players,
        started=True,
        phase=phase,
        **overrides,
    )


def standard_players():
    return [
        Player(id="p1", name="Alice", is_bot=True, role=Role.merlin),
        Player(id="p2", name="Bob", is_bot=True, role=Role.percival),
        Player(id="p3", name="Carol", is_bot=True, role=Role.loyal_servant),
        Player(id="p4", name="Dave", is_bot=True, role=Role.assassin),
        Player(id="p5", name="Eve", is_bot=True, role=Role.morgana),
    ]


# --- build_system_prompt ------------------------------------------------

@pytest.mark.parametrize("role", ALL_ROLES)
def test_system_prompt_builds_for_every_role(role):
    random.seed(0)
    player = Player(id="p1", name="Tester", role=role)
    prompt = build_system_prompt(player, knowledge=["Some fact"])
    assert "Tester" in prompt
    assert role.value in prompt
    assert "Some fact" in prompt
    # Alignment label is always present.
    assert "正义方" in prompt or "邪恶方" in prompt


def test_system_prompt_marks_evil_alignment_for_evil_roles():
    for role in (Role.assassin, Role.morgana, Role.mordred, Role.oberon, Role.minion):
        player = Player(id="p1", name="X", role=role)
        prompt = build_system_prompt(player, [])
        assert "你是邪恶方" in prompt


def test_system_prompt_gives_merlin_secrecy_guidance():
    prompt = build_system_prompt(Player(id="p1", name="M", role=Role.merlin), [])
    assert "梅林" in prompt
    assert "刺客" in prompt  # warned about being hunted


def test_system_prompt_handles_empty_knowledge():
    prompt = build_system_prompt(Player(id="p1", name="L", role=Role.loyal_servant), [])
    assert "- 无" in prompt


# --- build_context ------------------------------------------------------

def test_context_lists_roster_quest_and_leader():
    players = standard_players()
    state = make_state(players, quest_number=2, success_count=1, fail_count=0, leader_index=2)
    ctx = build_context(state, "p1", recent_chat=["Alice: hello"])
    for name in ("Alice", "Bob", "Carol", "Dave", "Eve"):
        assert name in ctx
    assert "任务 2" in ctx
    assert "队长：Carol" in ctx
    assert "Alice: hello" in ctx


def test_context_handles_no_chat_gracefully():
    state = make_state(standard_players())
    ctx = build_context(state, "p1", recent_chat=[])
    assert "（暂无聊天）" in ctx


def test_context_renders_quest_history_marks():
    from avalon.models import QuestRecord

    players = standard_players()
    state = make_state(
        players,
        quest_number=3,
        quest_history=[
            QuestRecord(quest_number=1, team=["p1", "p2"], fails=0, succeeded=True),
            QuestRecord(quest_number=2, team=["p3", "p4"], fails=1, succeeded=False),
        ],
    )
    ctx = build_context(state, "p1", [])
    assert "✓" in ctx and "✗" in ctx


# --- build_action_instructions ------------------------------------------

def test_team_proposal_instructions_demand_correct_size():
    state = make_state(standard_players(), phase=Phase.team_proposal, quest_number=1)
    leader = state.players[state.leader_index]
    text = build_action_instructions(state, leader)
    assert "TEAM:" in text
    assert "恰好 2 名玩家" in text  # 5-player quest 1 needs 2


def test_team_vote_instructions_present_proposed_team():
    state = make_state(
        standard_players(), phase=Phase.team_vote, proposed_team=["p1", "p2"]
    )
    text = build_action_instructions(state, state.players[2])
    assert "VOTE: APPROVE" in text
    assert "REJECT" in text
    assert "Alice" in text and "Bob" in text


def test_quest_instructions_force_loyal_success_and_allow_evil_fail():
    players = standard_players()
    state = make_state(players, phase=Phase.quest, proposed_team=["p1", "p4"])
    loyal_text = build_action_instructions(state, players[0])  # Merlin (loyal)
    assert '必须投"成功"' in loyal_text
    evil_text = build_action_instructions(state, players[3])  # Assassin (evil)
    assert '可以投"失败"' in evil_text


def test_assassination_targets_exclude_self_and_evil_teammates():
    players = standard_players()  # p4 assassin, p5 morgana are evil
    state = make_state(players, phase=Phase.assassination)
    assassin = players[3]
    text = build_action_instructions(state, assassin)
    # The good players are listed as possible targets...
    assert "Alice" in text and "Bob" in text and "Carol" in text
    # ...but the assassin's own name and the evil teammate never appear as targets.
    targets_line = next(
        line for line in text.splitlines() if line.startswith("可选目标：")
    )
    assert "Dave" not in targets_line  # self
    assert "Eve" not in targets_line  # evil teammate (Morgana)


def test_lady_of_lake_instructions_only_for_the_holder():
    players = standard_players()
    state = make_state(
        players, phase=Phase.lady_of_lake, lady_of_lake=True, lady_holder_id="p2"
    )
    holder_text = build_action_instructions(state, players[1])
    assert "INSPECT:" in holder_text
    # A non-holder gets the generic fallback, not the Lady task.
    other_text = build_action_instructions(state, players[0])
    assert "INSPECT:" not in other_text


def test_non_assassin_in_assassination_phase_gets_no_task():
    players = standard_players()
    state = make_state(players, phase=Phase.assassination)
    text = build_action_instructions(state, players[0])  # Merlin, not the assassin
    assert "TARGET:" not in text
