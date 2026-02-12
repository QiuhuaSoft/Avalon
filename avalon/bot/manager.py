from __future__ import annotations

import asyncio
from typing import List

from ..config import SETTINGS
from ..game import GameEngine
from ..models import Phase
from .policy import BotPolicy


class BotManager:
    def __init__(self, engine: GameEngine) -> None:
        self.engine = engine
        self.policy = BotPolicy()

    async def maybe_act(self) -> None:
        if SETTINGS.bot_mode == "external":
            return
        for _ in range(20):
            human_pending, bot_pending = self.engine.pending_actions()
            if human_pending or not bot_pending:
                return
            for bot_id in list(bot_pending):
                await self._act_bot(bot_id)
            await asyncio.sleep(0)

    async def _act_bot(self, bot_id: str) -> None:
        state = self.engine.state
        player = next(p for p in state.players if p.id == bot_id)
        knowledge = self.engine.knowledge_for(bot_id)
        decision = self.policy.decide(state, player, knowledge)
        action_type = decision.get("action_type")
        payload = decision.get("payload", {})
        if not isinstance(payload, dict):
            payload = {}

        # If the bot wants to say something, send chat first
        message = decision.get("message")
        if message and state.phase != Phase.lobby:
            await self.engine.apply_action(bot_id, "chat", {"message": message})

        # Then perform the actual action
        if action_type == "chat" and state.phase != Phase.lobby:
            await self.engine.apply_action(bot_id, action_type, payload)
            return
        await self.engine.apply_action(bot_id, action_type, payload)
