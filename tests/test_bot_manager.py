"""Bot-loop tests: deferral without chat spam, and full games terminating."""

import asyncio
import random

from helpers import ROLES_5, make_engine, started_engine

from avalon.bot.manager import BotManager
from avalon.bot.policy import ASSASSIN_DEFER_MESSAGE
from avalon.models import Alignment, CreateGameRequest, Phase, Player


def test_bot_assassin_defers_once_without_spamming_chat():
    async def scenario():
        # p4 = bot assassin, p5 = human minion, p1 = bot Merlin.
        engine = await started_engine(ROLES_5, bots=[True, True, True, True, False])
        engine.state.phase = Phase.assassination
        manager = BotManager(engine)

        await manager.maybe_act()
        assert [m.message for m in engine.state.chat] == [ASSASSIN_DEFER_MESSAGE]
        assert engine.state.assassin_target is None
        assert engine.state.phase == Phase.assassination

        # Repeated polls must not repeat the deferral message.
        await manager.maybe_act()
        await manager.maybe_act()
        assert len(engine.state.chat) == 1

    asyncio.run(scenario())


def test_bot_assassin_follows_human_evil_guidance_to_game_over():
    async def scenario():
        engine = await started_engine(ROLES_5, bots=[True, True, True, True, False])
        engine.state.phase = Phase.assassination
        manager = BotManager(engine)
        await manager.maybe_act()

        # The human minion names Merlin; the bot assassin should strike.
        await engine.apply_action("p5", "chat", {"message": "Go for P1."})
        await manager.maybe_act()

        state = engine.state
        assert state.assassin_target == "p1"
        assert state.phase == Phase.game_over
        assert state.winner == Alignment.evil

    asyncio.run(scenario())


def test_all_bot_game_runs_to_completion():
    async def scenario():
        random.seed(20260611)
        engine = make_engine()
        players = [Player(id=f"b{i}", name=f"Bot{i}", is_bot=True) for i in range(1, 6)]
        await engine.create_game(CreateGameRequest(players=players))
        await engine.start_game()
        manager = BotManager(engine)

        for _ in range(100):
            await manager.maybe_act()
            if engine.state.phase == Phase.game_over:
                break

        state = engine.state
        assert state.phase == Phase.game_over
        assert state.winner in (Alignment.loyal, Alignment.evil)
        assert len(state.quest_history) >= 3

    asyncio.run(scenario())
