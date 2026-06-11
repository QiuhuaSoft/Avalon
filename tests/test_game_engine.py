"""Rules-engine tests: role sets, voting, quests, and state redaction."""

import asyncio

import pytest
from helpers import (
    ROLES_5,
    ROLES_6,
    ROLES_7,
    event_types,
    propose,
    run_quest,
    started_engine,
    vote_team,
)

from avalon.game import DEFAULT_ROLE_SETS, EVIL_ROLES, team_size
from avalon.models import Alignment, Phase, Role

# Official The Resistance: Avalon evil-player counts per table size.
OFFICIAL_EVIL_COUNTS = {5: 2, 6: 2, 7: 3, 8: 3, 9: 3, 10: 4}


def test_default_role_sets_match_official_counts():
    for count, roles in DEFAULT_ROLE_SETS.items():
        assert len(roles) == count, f"{count}-player set has {len(roles)} roles"
        evil = sum(1 for role in roles if role in EVIL_ROLES)
        assert evil == OFFICIAL_EVIL_COUNTS[count], f"{count}-player set has {evil} evil"
        assert Role.merlin in roles and Role.assassin in roles
        if Role.morgana in roles:
            assert Role.percival in roles


def test_five_rejections_hand_evil_the_win():
    async def scenario():
        engine = await started_engine(ROLES_5, hammer_auto_approve=False)
        all_ids = [p.id for p in engine.state.players]
        for attempt in range(1, 6):
            state = engine.state
            leader = state.players[state.leader_index].id
            previous_leader_index = state.leader_index
            await propose(engine, [leader, all_ids[0] if all_ids[0] != leader else all_ids[1]])
            await vote_team(engine, {pid: False for pid in all_ids})
            state = engine.state
            assert state.proposal_attempts == attempt
            if attempt < 5:
                assert state.phase == Phase.team_proposal
                assert state.leader_index == (previous_leader_index + 1) % 5
            else:
                assert state.phase == Phase.game_over
                assert state.winner == Alignment.evil
        assert "five_rejections" in event_types(engine)

    asyncio.run(scenario())


def test_hammer_auto_approves_fifth_proposal():
    async def scenario():
        engine = await started_engine(ROLES_5, hammer_auto_approve=True)
        all_ids = [p.id for p in engine.state.players]
        for _ in range(4):
            state = engine.state
            leader = state.players[state.leader_index].id
            other = all_ids[0] if all_ids[0] != leader else all_ids[1]
            await propose(engine, [leader, other])
            await vote_team(engine, {pid: False for pid in all_ids})
        state = engine.state
        assert state.proposal_attempts == 4
        leader = state.players[state.leader_index].id
        other = all_ids[0] if all_ids[0] != leader else all_ids[1]
        await propose(engine, [leader, other])
        state = engine.state
        assert state.phase == Phase.quest
        assert "team_hammered" in event_types(engine)

    asyncio.run(scenario())


def test_tied_team_vote_is_rejected():
    async def scenario():
        engine = await started_engine(ROLES_6)
        all_ids = [p.id for p in engine.state.players]
        await propose(engine, ["p1", "p2"])
        votes = {pid: idx < 3 for idx, pid in enumerate(all_ids)}
        await vote_team(engine, votes)
        state = engine.state
        assert state.phase == Phase.team_proposal
        assert state.proposal_attempts == 1

    asyncio.run(scenario())


def test_loyal_players_cannot_fail_quests():
    async def scenario():
        engine = await started_engine(ROLES_5)
        all_ids = [p.id for p in engine.state.players]
        await propose(engine, ["p1", "p4"])  # Merlin + Assassin
        await vote_team(engine, {pid: True for pid in all_ids})
        with pytest.raises(ValueError, match="must submit success"):
            await engine.apply_action("p1", "quest_vote", {"success": False})
        # The assassin is free to fail.
        await run_quest(engine, {"p1": True, "p4": False})
        state = engine.state
        assert state.quest_history[-1].fails == 1
        assert not state.quest_history[-1].succeeded

    asyncio.run(scenario())


def test_quest_four_needs_two_fails_with_seven_players():
    async def single_fail_succeeds():
        engine = await started_engine(ROLES_7)
        engine.state.quest_number = 4
        size = team_size(7, 4)
        team = ["p1", "p2", "p3", "p5"]  # one evil (assassin)
        assert len(team) == size
        await propose(engine, team)
        await vote_team(engine, {p.id: True for p in engine.state.players})
        await run_quest(engine, {"p1": True, "p2": True, "p3": True, "p5": False})
        record = engine.state.quest_history[-1]
        assert record.fails == 1 and record.succeeded

    async def two_fails_fail():
        engine = await started_engine(ROLES_7)
        engine.state.quest_number = 4
        team = ["p1", "p2", "p5", "p6"]  # two evil
        await propose(engine, team)
        await vote_team(engine, {p.id: True for p in engine.state.players})
        await run_quest(engine, {"p1": True, "p2": True, "p5": False, "p6": False})
        record = engine.state.quest_history[-1]
        assert record.fails == 2 and not record.succeeded

    asyncio.run(single_fail_succeeds())
    asyncio.run(two_fails_fail())


def test_third_success_triggers_assassination_and_merlin_hit_decides():
    async def scenario(target: str, expected_winner: Alignment):
        engine = await started_engine(ROLES_5)
        engine.state.success_count = 2
        await propose(engine, ["p1", "p2"])
        await vote_team(engine, {p.id: True for p in engine.state.players})
        await run_quest(engine, {"p1": True, "p2": True})
        state = engine.state
        assert state.phase == Phase.assassination
        with pytest.raises(ValueError, match="Only assassin"):
            await engine.apply_action("p1", "assassinate", {"target_id": "p2"})
        await engine.apply_action("p4", "assassinate", {"target_id": target})
        state = engine.state
        assert state.phase == Phase.game_over
        assert state.winner == expected_winner

    asyncio.run(scenario("p1", Alignment.evil))  # p1 is Merlin
    asyncio.run(scenario("p2", Alignment.loyal))


def test_third_failed_quest_ends_game_for_evil():
    async def scenario():
        engine = await started_engine(ROLES_5)
        engine.state.fail_count = 2
        await propose(engine, ["p1", "p4"])
        await vote_team(engine, {p.id: True for p in engine.state.players})
        await run_quest(engine, {"p1": True, "p4": False})
        state = engine.state
        assert state.phase == Phase.game_over
        assert state.winner == Alignment.evil

    asyncio.run(scenario())


def test_open_team_votes_hidden_from_everyone_but_the_voter():
    async def scenario():
        engine = await started_engine(ROLES_5)
        await propose(engine, ["p1", "p2"])
        await vote_team(engine, {"p1": True, "p2": False})
        assert engine.state.phase == Phase.team_vote
        assert engine.public_state().team_votes == {}
        assert engine.public_state(viewer_id="p1").team_votes == {"p1": True}
        assert engine.public_state(viewer_id="p3").team_votes == {}
        private = engine.private_state_for("p2")
        assert private["state"].team_votes == {"p2": False}

    asyncio.run(scenario())


def test_team_votes_become_public_once_resolved():
    async def scenario():
        engine = await started_engine(ROLES_5)
        await propose(engine, ["p1", "p2"])
        votes = {"p1": True, "p2": True, "p3": True, "p4": False, "p5": False}
        await vote_team(engine, votes)
        state = engine.state
        assert state.phase == Phase.quest
        assert engine.public_state().team_votes == votes

    asyncio.run(scenario())


def test_quest_votes_never_revealed():
    async def scenario():
        engine = await started_engine(ROLES_5)
        await propose(engine, ["p1", "p4"])
        await vote_team(engine, {p.id: True for p in engine.state.players})
        await engine.apply_action("p1", "quest_vote", {"success": True})
        assert engine.public_state().quest_votes == {}
        assert engine.public_state(viewer_id="p1").quest_votes == {"p1": True}
        assert engine.public_state(viewer_id="p4").quest_votes == {}

    asyncio.run(scenario())


def test_public_state_strips_roles_and_lady_history():
    async def scenario():
        engine = await started_engine(ROLES_5)
        engine.state.lady_history.append(
            {"holder_id": "p1", "target_id": "p4", "alignment": "evil"}
        )
        public = engine.public_state()
        assert all(p.role is None for p in public.players)
        assert public.lady_history == []
        private = engine.private_state_for("p4")
        roles = {p.id: p.role for p in private["state"].players}
        assert roles["p4"] == Role.assassin
        assert all(role is None for pid, role in roles.items() if pid != "p4")

    asyncio.run(scenario())


def test_create_game_validates_roles():
    from helpers import make_engine

    from avalon.models import CreateGameRequest, Player

    def players(count):
        return [Player(id=f"p{i + 1}", name=f"P{i + 1}") for i in range(count)]

    async def scenario():
        with pytest.raises(ValueError, match="Unsupported player count"):
            await make_engine().create_game(CreateGameRequest(players=players(4)))
        with pytest.raises(ValueError, match="match player count"):
            await make_engine().create_game(
                CreateGameRequest(players=players(5), roles=ROLES_6)
            )
        with pytest.raises(ValueError, match="Morgana requires Percival"):
            await make_engine().create_game(
                CreateGameRequest(
                    players=players(5),
                    roles=[
                        Role.merlin,
                        Role.loyal_servant,
                        Role.loyal_servant,
                        Role.assassin,
                        Role.morgana,
                    ],
                )
            )
        with pytest.raises(ValueError, match="Merlin and Assassin"):
            await make_engine().create_game(
                CreateGameRequest(
                    players=players(5),
                    roles=[
                        Role.merlin,
                        Role.percival,
                        Role.loyal_servant,
                        Role.loyal_servant,
                        Role.minion,
                    ],
                )
            )

    asyncio.run(scenario())
