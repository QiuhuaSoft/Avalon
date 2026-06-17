"""Lady of the Lake: timing, the holder's private knowledge, and token passing.

This is the most stateful path in the engine — it interleaves with quest
resolution, leader rotation, and per-player knowledge — so it gets a dedicated
end-to-end walk rather than a single assertion.
"""

import asyncio

import pytest
from helpers import ROLES_7, propose, run_quest, started_engine, vote_team

from avalon.models import Phase


async def _approve_and_run(engine, team, votes):
    await propose(engine, team)
    await vote_team(engine, {p.id: True for p in engine.state.players})
    await run_quest(engine, votes)


def test_lady_triggers_after_quest_two_and_passes_the_token():
    async def scenario():
        # ROLES_7 in order: p1 Merlin, p2 Percival, p3/p4 Loyal, p5 Assassin,
        # p6 Morgana, p7 Minion. Lady starts with p1.
        engine = await started_engine(ROLES_7, lady_of_lake=True)
        assert engine.state.lady_holder_id == "p1"

        # Quest 1 (team size 2): no Lady before quests 1 or 2.
        await _approve_and_run(engine, ["p1", "p2"], {"p1": True, "p2": True})
        assert engine.state.phase == Phase.team_proposal
        assert engine.state.quest_number == 2

        # Quest 2 (team size 3) succeeds -> Lady phase opens before quest 3.
        await _approve_and_run(engine, ["p1", "p2", "p3"], {"p1": True, "p2": True, "p3": True})
        state = engine.state
        assert state.phase == Phase.lady_of_lake
        assert state.quest_number == 3
        assert state.lady_holder_id == "p1"

        # Only the holder may act, and not on themselves.
        humans, _ = engine.pending_actions()
        assert humans == ["p1"]
        with pytest.raises(ValueError, match="Only the Lady holder"):
            await engine.apply_action("p2", "lady_peek", {"target_id": "p3"})
        with pytest.raises(ValueError, match="Cannot target yourself"):
            await engine.apply_action("p1", "lady_peek", {"target_id": "p1"})

        # p1 inspects the Assassin (p5, evil): learns the true alignment and the
        # token moves to p5.
        await engine.apply_action("p1", "lady_peek", {"target_id": "p5"})
        state = engine.state
        assert state.phase == Phase.team_proposal
        assert state.lady_holder_id == "p5"
        knowledge = engine.private_state_for("p1")["lady_knowledge"]
        assert any("evil" in line for line in knowledge)
        # The peek result is private to the holder, never the target.
        assert engine.private_state_for("p5")["lady_knowledge"] == []

        # The peek is not allowed once we leave the Lady phase.
        with pytest.raises(ValueError, match="Not in Lady of the Lake phase"):
            await engine.apply_action("p5", "lady_peek", {"target_id": "p2"})

    asyncio.run(scenario())


def test_lady_recurs_before_quest_four_with_the_new_holder():
    async def scenario():
        engine = await started_engine(ROLES_7, lady_of_lake=True)
        await _approve_and_run(engine, ["p1", "p2"], {"p1": True, "p2": True})
        await _approve_and_run(engine, ["p1", "p2", "p3"], {"p1": True, "p2": True, "p3": True})
        # First Lady use: p1 -> token to p5.
        await engine.apply_action("p1", "lady_peek", {"target_id": "p5"})

        # Quest 3 (team size 3) fails via the Assassin so the game continues to
        # quest 4 rather than ending at three successes.
        await _approve_and_run(engine, ["p1", "p3", "p5"], {"p1": True, "p3": True, "p5": False})
        state = engine.state
        assert state.quest_history[-1].succeeded is False
        assert state.success_count == 2 and state.fail_count == 1

        # Lady opens again before quest 4, now held by p5.
        assert state.phase == Phase.lady_of_lake
        assert state.quest_number == 4
        assert state.lady_holder_id == "p5"

        await engine.apply_action("p5", "lady_peek", {"target_id": "p2"})
        assert engine.state.lady_holder_id == "p2"
        assert engine.state.phase == Phase.team_proposal

    asyncio.run(scenario())


def test_disabled_lady_never_opens_the_phase():
    async def scenario():
        engine = await started_engine(ROLES_7, lady_of_lake=False)
        assert engine.state.lady_holder_id is None
        await _approve_and_run(engine, ["p1", "p2"], {"p1": True, "p2": True})
        await _approve_and_run(engine, ["p1", "p2", "p3"], {"p1": True, "p2": True, "p3": True})
        # Straight to the next proposal — no Lady detour.
        assert engine.state.phase == Phase.team_proposal
        with pytest.raises(ValueError, match="Lady of the Lake is disabled"):
            # Force the phase to prove the guard, not just the scheduling.
            engine.state.phase = Phase.lady_of_lake
            await engine.apply_action("p1", "lady_peek", {"target_id": "p2"})

    asyncio.run(scenario())


def test_loyal_role_reads_as_loyal_through_the_lady():
    async def scenario():
        engine = await started_engine(ROLES_7, lady_of_lake=True)
        await _approve_and_run(engine, ["p1", "p2"], {"p1": True, "p2": True})
        await _approve_and_run(engine, ["p1", "p2", "p3"], {"p1": True, "p2": True, "p3": True})
        # p1 inspects p3 (a Loyal Servant).
        await engine.apply_action("p1", "lady_peek", {"target_id": "p3"})
        knowledge = engine.private_state_for("p1")["lady_knowledge"]
        assert any("loyal" in line for line in knowledge)

    asyncio.run(scenario())
