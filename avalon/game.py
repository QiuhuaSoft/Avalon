from __future__ import annotations

import asyncio
import random
import uuid
from typing import Any, Dict, List, Optional, Tuple, overload

from .models import (
    Alignment,
    ChatMessage,
    CreateGameRequest,
    Event,
    GameConfig,
    GameState,
    Phase,
    Player,
    QuestRecord,
    Role,
)
from .storage import EventStore

EVIL_ROLES = {Role.assassin, Role.morgana, Role.mordred, Role.oberon, Role.minion}

# Avalon is defined for 5-10 players; the quest-size and role tables below have no
# rows outside that range, so a game built outside it cannot be played.
MIN_PLAYERS = 5
MAX_PLAYERS = 10

# Caps on untrusted free text. Chat and names arrive from remote players (over a
# tunnel, authenticated only by a per-player token) and are echoed into every
# public-state snapshot, which is deep-copied on each poll/stream tick. Bounding
# them keeps one client from amplifying memory and bandwidth for everyone.
MAX_CHAT_LENGTH = 1000
MAX_NAME_LENGTH = 60

QUEST_TEAM_SIZES = {
    5: [2, 3, 2, 3, 3],
    6: [2, 3, 4, 3, 4],
    7: [2, 3, 3, 4, 4],
    8: [3, 4, 4, 5, 5],
    9: [3, 4, 4, 5, 5],
    10: [3, 4, 4, 5, 5],
}

DEFAULT_ROLE_SETS = {
    5: [Role.merlin, Role.percival, Role.loyal_servant, Role.assassin, Role.minion],
    6: [
        Role.merlin,
        Role.percival,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.assassin,
        Role.morgana,
    ],
    7: [
        Role.merlin,
        Role.percival,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.assassin,
        Role.morgana,
        Role.minion,
    ],
    # Official Avalon alignment counts: 8 players = 3 evil, 9 = 3 evil, 10 = 4 evil.
    8: [
        Role.merlin,
        Role.percival,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.assassin,
        Role.morgana,
        Role.minion,
    ],
    9: [
        Role.merlin,
        Role.percival,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.assassin,
        Role.morgana,
        Role.mordred,
    ],
    10: [
        Role.merlin,
        Role.percival,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.loyal_servant,
        Role.assassin,
        Role.morgana,
        Role.mordred,
        Role.oberon,
    ],
}


@overload
def alignment_for(role: Role) -> Alignment: ...
@overload
def alignment_for(role: None) -> None: ...
def alignment_for(role: Optional[Role]) -> Optional[Alignment]:
    # An unassigned role has no alignment. Returning None (rather than defaulting
    # to loyal) keeps callers from mislabelling a role-less player as good.
    if role is None:
        return None
    if role in EVIL_ROLES:
        return Alignment.evil
    return Alignment.loyal


def requires_two_fails(player_count: int, quest_number: int) -> bool:
    return player_count >= 7 and quest_number == 4


def team_size(player_count: int, quest_number: int) -> int:
    sizes = QUEST_TEAM_SIZES.get(player_count)
    if not sizes:
        raise ValueError("不支持的玩家数量")
    return sizes[quest_number - 1]


class GameNotCreatedError(RuntimeError):
    """Raised when an operation needs an active game but none has been created.

    Subclasses ``RuntimeError`` so it stays a programming-invariant error and any
    existing ``except RuntimeError`` keeps catching it, while giving the HTTP
    layer a precise type to reshape into a clean 400 (other, unexpected
    RuntimeErrors still surface as 500s, the way an internal fault should).
    """


class GameEngine:
    def __init__(self, store: EventStore) -> None:
        self._store = store
        self._state: Optional[GameState] = None
        self._lock = asyncio.Lock()
        self._token_by_player_id: Dict[str, str] = {}
        self._player_id_by_token: Dict[str, str] = {}
        self._host_token: Optional[str] = None

    @property
    def state(self) -> GameState:
        if not self._state:
            raise GameNotCreatedError("没有进行中的游戏")
        return self._state

    def has_state(self) -> bool:
        return self._state is not None

    async def create_game(self, req: CreateGameRequest) -> GameState:
        async with self._lock:
            player_count = len(req.players)
            if player_count < MIN_PLAYERS or player_count > MAX_PLAYERS:
                raise ValueError(
                    "不支持的玩家数量："
                    f"阿瓦隆支持 {MIN_PLAYERS}-{MAX_PLAYERS} 人游戏"
                )
            ids = [p.id for p in req.players]
            if any(not pid for pid in ids):
                raise ValueError("玩家ID不能为空")
            if len(set(ids)) != len(ids):
                raise ValueError("玩家ID不能重复")
            # player_count is in range, so a default set always exists.
            roles = req.roles or DEFAULT_ROLE_SETS[player_count]
            if len(roles) != player_count:
                raise ValueError("角色数量必须与玩家数量匹配")
            if Role.morgana in roles and Role.percival not in roles:
                raise ValueError("莫甘娜需要派西维尔同时在场")
            if Role.merlin not in roles or Role.assassin not in roles:
                raise ValueError("梅林和刺客是必选角色")
            config = GameConfig(
                player_count=player_count,
                roles=roles,
                hammer_auto_approve=req.hammer_auto_approve,
                lady_of_lake=req.lady_of_lake,
            )
            self._store.clear()
            self._token_by_player_id = {}
            self._player_id_by_token = {}
            self._host_token = str(uuid.uuid4())
            self._state = GameState(
                id=str(uuid.uuid4()),
                config=config,
                players=req.players,
                started=False,
                phase=Phase.lobby,
            )
            for player in self._state.players:
                self._assign_token(player.id)
            self._emit("game_created", {"player_count": player_count})
            return self.state

    async def start_game(self) -> GameState:
        async with self._lock:
            state = self.state
            if state.started:
                return state
            random.shuffle(state.players)
            self._assign_roles(state)
            state.started = True
            state.phase = Phase.team_proposal
            state.leader_index = 0
            state.quest_number = 1
            state.proposal_attempts = 0
            state.lady_holder_id = state.players[0].id if state.config.lady_of_lake else None
            state.lady_last_used_quest = None
            state.lady_history = []
            self._emit("game_started", {})
            return state

    async def apply_action(
        self, player_id: str, action_type: str, payload: Dict[str, Any]
    ) -> GameState:
        async with self._lock:
            state = self.state
            player = self._get_player(player_id)
            if action_type == "chat":
                message = payload.get("message", "")
                if not isinstance(message, str) or not message.strip():
                    raise ValueError("消息不能为空")
                if len(message) > MAX_CHAT_LENGTH:
                    raise ValueError(f"消息过长（最多 {MAX_CHAT_LENGTH} 个字符）")
                if state.phase == Phase.assassination and player.role not in EVIL_ROLES:
                    raise ValueError("刺杀阶段只有邪恶方玩家可以聊天")
                state.chat.append(ChatMessage(player_id=player_id, message=message))
                self._emit("chat", {"player_id": player_id, "message": message})
                return state

            if not state.started:
                raise ValueError("游戏尚未开始")

            if action_type == "propose_team":
                return self._handle_propose(state, player, payload)
            if action_type == "vote_team":
                return self._handle_vote(state, player, payload)
            if action_type == "quest_vote":
                return self._handle_quest_vote(state, player, payload)
            if action_type == "lady_peek":
                return self._handle_lady(state, player, payload)
            if action_type == "assassinate":
                return self._handle_assassinate(state, player, payload)

            raise ValueError(f"未知操作：{action_type}")

    async def add_player(self, is_bot: bool, name: Optional[str]) -> GameState:
        async with self._lock:
            state = self.state
            if state.started:
                raise ValueError("游戏已经开始")
            if len(state.players) >= MAX_PLAYERS:
                raise ValueError("已达最大玩家数")
            prefix = "b" if is_bot else "h"
            next_id = self._next_id(prefix)
            default_name = f"机器人{next_id[1:]}" if is_bot else f"玩家{next_id[1:]}"
            display_name = self._clean_name(name) if name else default_name
            state.players.append(Player(id=next_id, name=display_name, is_bot=is_bot))
            self._assign_token(next_id)
            self._emit("player_added", {"player_id": next_id, "is_bot": is_bot})
            return state

    async def remove_player(self, player_id: str) -> GameState:
        async with self._lock:
            state = self.state
            if state.started:
                raise ValueError("游戏已经开始")
            if not self._has_player(player_id):
                raise ValueError("未知玩家")
            state.players = [p for p in state.players if p.id != player_id]
            self._clear_token(player_id)
            self._emit("player_removed", {"player_id": player_id})
            return state

    async def rename_player(self, player_id: str, name: str) -> GameState:
        async with self._lock:
            state = self.state
            if state.started:
                raise ValueError("游戏已经开始")
            player = self._get_player(player_id)
            player.name = self._clean_name(name)
            self._emit("player_renamed", {"player_id": player_id, "name": player.name})
            return state

    async def join_next_human(self, name: str) -> Player:
        async with self._lock:
            state = self.state
            if state.started:
                raise ValueError("游戏已经开始")
            for player in state.players:
                if not player.is_bot and not player.claimed:
                    player.claimed = True
                    player.ready = False
                    player.name = self._clean_name(name)
                    self._emit("player_claimed", {"player_id": player.id, "name": player.name})
                    return player
            raise ValueError("没有可用的人类座位")

    async def set_ready(self, player_id: str, ready: bool) -> GameState:
        async with self._lock:
            state = self.state
            player = self._get_player(player_id)
            if player.is_bot:
                raise ValueError("机器人不能准备")
            player.ready = ready
            self._emit("player_ready", {"player_id": player_id, "ready": ready})
            return state

    async def remove_last_human_slot(self) -> GameState:
        async with self._lock:
            state = self.state
            if state.started:
                raise ValueError("游戏已经开始")
            humans = [p for p in state.players if not p.is_bot]
            if not humans:
                raise ValueError("没有可移除的人类座位")
            for candidate in reversed(humans):
                if not candidate.claimed:
                    state.players = [p for p in state.players if p.id != candidate.id]
                    self._emit("player_removed", {"player_id": candidate.id})
                    return state
            raise ValueError("所有人类座位已被占用")
    async def reset_player(self, player_id: str) -> GameState:
        async with self._lock:
            state = self.state
            if state.started:
                raise ValueError("游戏已经开始")
            player = self._get_player(player_id)
            player.claimed = False
            player.ready = False
            self._rotate_token(player_id)
            suffix = player.id[1:] if len(player.id) > 1 else ""
            player.name = f"机器人{suffix}" if player.is_bot else f"玩家{suffix}"
            self._emit("player_reset", {"player_id": player_id})
            return state

    def public_state(self, viewer_id: Optional[str] = None) -> GameState:
        state = self.state.model_copy(deep=True)
        # Once the game is over the hidden-role veil lifts: every player's role
        # and the full Lady-of-the-Lake history become public knowledge, the way
        # a tabletop game ends with everyone flipping their role card. Until then
        # roles are stripped from every snapshot. (Individual quest ballots stay
        # secret even after the reveal — the physical quest cards are shuffled,
        # so who failed a mission is never known; only the fail counts are.)
        if state.phase != Phase.game_over:
            for p in state.players:
                p.role = None
            state.lady_history = []
        # Team votes are revealed simultaneously: while the vote is open only the
        # viewer's own ballot is visible. Once resolved (approved team carries its
        # votes into the quest phase) they are public record.
        if state.phase == Phase.team_vote:
            state.team_votes = {
                pid: vote for pid, vote in state.team_votes.items() if pid == viewer_id
            }
        # Quest votes are secret forever; only the aggregate fail count is public.
        state.quest_votes = {
            pid: vote for pid, vote in state.quest_votes.items() if pid == viewer_id
        }
        return state

    def private_state_for(self, player_id: str) -> Dict[str, Any]:
        state = self.public_state(viewer_id=player_id)
        player = self._get_player(player_id)
        for p in state.players:
            if p.id == player_id:
                p.role = player.role
        return {
            "state": state,
            "role": player.role,
            "knowledge": self._knowledge_for(player_id),
            "alignment": alignment_for(player.role) if player.role else None,
            "visibility": self._visibility_for(player_id),
            "lady_knowledge": self._lady_knowledge_for(player_id),
        }

    def knowledge_for(self, player_id: str) -> List[str]:
        return self._knowledge_for(player_id)

    def _assign_roles(self, state: GameState) -> None:
        roles = list(state.config.roles)
        random.shuffle(roles)
        for player, role in zip(state.players, roles):
            player.role = role

    def _handle_propose(
        self, state: GameState, player: Player, payload: Dict[str, Any]
    ) -> GameState:
        if state.phase != Phase.team_proposal:
            raise ValueError("当前不是组队提议阶段")
        leader = state.players[state.leader_index]
        if player.id != leader.id:
            raise ValueError("只有队长可以提议队伍")
        team = payload.get("team", [])
        if not isinstance(team, list):
            raise ValueError("队伍必须是玩家ID列表")
        size = team_size(state.config.player_count, state.quest_number)
        if len(team) != size:
            raise ValueError("队伍人数不正确")
        if len(set(team)) != len(team):
            raise ValueError("队伍中有重复玩家")
        if not all(self._has_player(pid) for pid in team):
            raise ValueError("队伍中有未知玩家")
        state.proposed_team = team
        state.team_votes = {}
        self._emit("team_proposed", {"leader_id": leader.id, "team": team})

        if state.config.hammer_auto_approve and state.proposal_attempts >= 4:
            state.phase = Phase.quest
            self._emit("team_hammered", {"team": team})
        else:
            state.phase = Phase.team_vote
        return state

    def _handle_vote(self, state: GameState, player: Player, payload: Dict[str, Any]) -> GameState:
        if state.phase != Phase.team_vote:
            raise ValueError("当前不是投票表决阶段")
        approve = payload.get("approve")
        if not isinstance(approve, bool):
            raise ValueError("投票必须是布尔值")
        # A team ballot is committed on its first cast — Avalon votes are
        # simultaneous and final. Ignore a resubmission so a double-click or
        # retry cannot flip an already-committed vote or emit a second ballot
        # event (the public log keeps exactly one team_vote per player here).
        if player.id in state.team_votes:
            return state
        state.team_votes[player.id] = approve
        self._emit("team_vote", {"player_id": player.id, "approve": approve})
        if len(state.team_votes) < len(state.players):
            return state

        approvals = sum(1 for v in state.team_votes.values() if v)
        rejects = len(state.players) - approvals
        if approvals > rejects:
            state.phase = Phase.quest
            state.proposal_attempts = 0
            self._emit("team_approved", {"approvals": approvals, "rejects": rejects})
        else:
            state.proposal_attempts += 1
            state.proposed_team = []
            state.team_votes = {}
            self._emit("team_rejected", {"approvals": approvals, "rejects": rejects})
            # Official rule: five consecutive rejected proposals hand evil the win.
            # Only reachable with the hammer disabled (the hammer auto-approves the
            # fifth proposal before it can be voted down).
            if state.proposal_attempts >= 5:
                state.phase = Phase.game_over
                state.winner = Alignment.evil
                self._emit("five_rejections", {"quest": state.quest_number})
            else:
                state.phase = Phase.team_proposal
                state.leader_index = (state.leader_index + 1) % len(state.players)
        return state

    def _handle_quest_vote(
        self, state: GameState, player: Player, payload: Dict[str, Any]
    ) -> GameState:
        if state.phase != Phase.quest:
            raise ValueError("当前不是执行任务阶段")
        if player.id not in state.proposed_team:
            raise ValueError("只有队伍成员可以投票")
        success = payload.get("success")
        if not isinstance(success, bool):
            raise ValueError("任务投票必须是布尔值")
        if player.role and alignment_for(player.role) == Alignment.loyal and not success:
            raise ValueError("正义方玩家必须投成功")
        # Quest cards are committed on first submission: ignore a resubmission so
        # a double-click cannot swap a played card or double-count toward
        # resolution. The first card a team member plays is the one that counts.
        if player.id in state.quest_votes:
            return state
        state.quest_votes[player.id] = success
        self._emit("quest_vote", {"player_id": player.id, "success": success})
        if len(state.quest_votes) < len(state.proposed_team):
            return state

        fails = sum(1 for v in state.quest_votes.values() if not v)
        needed = 2 if requires_two_fails(state.config.player_count, state.quest_number) else 1
        succeeded = fails < needed
        state.quest_history.append(
            QuestRecord(
                quest_number=state.quest_number,
                team=list(state.proposed_team),
                fails=fails,
                succeeded=succeeded,
            )
        )
        if succeeded:
            state.success_count += 1
        else:
            state.fail_count += 1
        self._emit(
            "quest_resolved",
            {"quest": state.quest_number, "fails": fails, "succeeded": succeeded},
        )

        state.proposed_team = []
        state.team_votes = {}
        state.quest_votes = {}

        if state.success_count >= 3:
            if any(p.role == Role.merlin for p in state.players):
                state.phase = Phase.assassination
            else:
                state.phase = Phase.game_over
                state.winner = Alignment.loyal
            return state
        if state.fail_count >= 3:
            state.phase = Phase.game_over
            state.winner = Alignment.evil
            return state

        state.quest_number += 1
        state.leader_index = (state.leader_index + 1) % len(state.players)
        state.proposal_attempts = 0
        if (
            state.config.lady_of_lake
            and state.quest_number >= 3
            and state.lady_last_used_quest != state.quest_number - 1
        ):
            state.phase = Phase.lady_of_lake
        else:
            state.phase = Phase.team_proposal
        return state

    def _handle_lady(self, state: GameState, player: Player, payload: Dict[str, Any]) -> GameState:
        if state.phase != Phase.lady_of_lake:
            raise ValueError("当前不是湖中夫人阶段")
        if not state.config.lady_of_lake:
            raise ValueError("湖中夫人功能已禁用")
        if state.lady_holder_id != player.id:
            raise ValueError("只有湖中夫人持有者可以操作")
        target_id = payload.get("target_id")
        if not target_id or not self._has_player(target_id):
            raise ValueError("需要有效的目标ID")
        if target_id == player.id:
            raise ValueError("不能调查自己")
        # Official rule: the Lady of the Lake may not be used on anyone who has
        # already held it. Every past holder appears as a `holder_id` in the peek
        # history (the current holder is caught by the self-check above), so this
        # also stops the token bouncing back and forth between two players.
        if any(entry["holder_id"] == target_id for entry in state.lady_history):
            raise ValueError("不能调查曾经持有湖中夫人的玩家")
        target = self._get_player(target_id)
        alignment = alignment_for(target.role).value if target.role else "unknown"
        state.lady_history.append(
            {"holder_id": player.id, "target_id": target_id, "alignment": alignment}
        )
        state.lady_holder_id = target_id
        state.lady_last_used_quest = state.quest_number - 1
        state.phase = Phase.team_proposal
        self._emit("lady_peek", {"holder_id": player.id, "target_id": target_id})
        return state

    def _handle_assassinate(
        self, state: GameState, player: Player, payload: Dict[str, Any]
    ) -> GameState:
        if state.phase != Phase.assassination:
            raise ValueError("当前不是刺杀阶段")
        if player.role != Role.assassin:
            raise ValueError("只有刺客可以执行刺杀")
        target_id = payload.get("target_id")
        if not target_id or not self._has_player(target_id):
            raise ValueError("需要有效的目标ID")
        if target_id == player.id:
            raise ValueError("刺客不能刺杀自己")
        target = self._get_player(target_id)
        # The assassin already knows every evil teammate except Oberon, so naming
        # one can only forfeit the game. Reject it. Oberon is intentionally
        # excluded: the assassin cannot tell Oberon from a good player, and
        # rejecting an Oberon shot would leak that hidden alignment.
        if target.role in EVIL_ROLES and target.role != Role.oberon:
            raise ValueError("刺客不能刺杀已知的邪恶方队友")
        state.assassin_target = target_id
        if target.role == Role.merlin:
            state.winner = Alignment.evil
        else:
            state.winner = Alignment.loyal
        state.phase = Phase.game_over
        self._emit("assassination", {"target_id": target_id, "hit": target.role == Role.merlin})
        return state

    def pending_actions(self) -> Tuple[List[str], List[str]]:
        state = self.state
        human_pending: List[str] = []
        bot_pending: List[str] = []

        def add_pending(pid: str) -> None:
            player = self._get_player(pid)
            if player.is_bot:
                bot_pending.append(pid)
            else:
                human_pending.append(pid)

        if state.phase == Phase.team_proposal:
            leader = state.players[state.leader_index].id
            if not state.proposed_team:
                add_pending(leader)
        elif state.phase == Phase.team_vote:
            for p in state.players:
                if p.id not in state.team_votes:
                    add_pending(p.id)
        elif state.phase == Phase.quest:
            for pid in state.proposed_team:
                if pid not in state.quest_votes:
                    add_pending(pid)
        elif state.phase == Phase.assassination:
            assassin = next((p for p in state.players if p.role == Role.assassin), None)
            if assassin and not state.assassin_target:
                add_pending(assassin.id)
        elif state.phase == Phase.lady_of_lake:
            if state.lady_holder_id:
                add_pending(state.lady_holder_id)
        return human_pending, bot_pending

    def _knowledge_for(self, player_id: str) -> List[str]:
        player = self._get_player(player_id)
        if not player.role:
            return []
        evil_known = [
            p for p in self.state.players if p.role in EVIL_ROLES and p.role != Role.oberon
        ]
        if player.role in EVIL_ROLES and player.role != Role.oberon:
            others = [p.name for p in evil_known if p.id != player.id]
            return ["已知的邪恶方玩家（不含奥伯伦）：" + ", ".join(others)] if others else []
        if player.role == Role.oberon:
            return ["你是奥伯伦：邪恶方成员，但其他邪恶方玩家不知道你的身份。"]
        if player.role == Role.merlin:
            seen = [
                p.name
                for p in self.state.players
                if p.role in EVIL_ROLES and p.role != Role.mordred
            ]
            return (
                ["你看到的邪恶方玩家（不含莫德雷德）：" + ", ".join(seen)] if seen else []
            )
        if player.role == Role.percival:
            merlin = [p.name for p in self.state.players if p.role == Role.merlin]
            morgana = [p.name for p in self.state.players if p.role == Role.morgana]
            candidates = merlin + morgana
            if candidates:
                return ["梅林是其中之一：" + ", ".join(candidates)]
        return []

    def _lady_knowledge_for(self, player_id: str) -> List[str]:
        knowledge: List[str] = []
        alignment_map = {"loyal": "正义方", "evil": "邪恶方"}
        for entry in self.state.lady_history:
            if entry["holder_id"] == player_id:
                target = self._get_player(entry["target_id"])
                alignment_str = alignment_map.get(entry['alignment'], entry['alignment'])
                knowledge.append(
                    f"湖中夫人：{target.name} 是 {alignment_str}。"
                )
        return knowledge

    def _visibility_for(self, player_id: str) -> List[Dict[str, Any]]:
        player = self._get_player(player_id)
        visibility: List[Dict[str, Any]] = []
        for p in self.state.players:
            entry: Dict[str, Any] = {
                "id": p.id,
                "name": p.name,
                "alignment_hint": "unknown",
                "role_hint": None,
            }
            visibility.append(entry)

        if not player.role:
            return visibility

        if player.role in EVIL_ROLES and player.role != Role.oberon:
            for entry in visibility:
                target = self._get_player(entry["id"])
                if target.role in EVIL_ROLES and target.role != Role.oberon:
                    entry["alignment_hint"] = "evil"
            return visibility

        if player.role == Role.oberon:
            entry = next(e for e in visibility if e["id"] == player_id)
            entry["alignment_hint"] = "evil"
            return visibility

        if player.role == Role.merlin:
            for entry in visibility:
                target = self._get_player(entry["id"])
                if target.role in EVIL_ROLES and target.role != Role.mordred:
                    entry["alignment_hint"] = "evil"
            return visibility

        if player.role == Role.percival:
            for entry in visibility:
                target = self._get_player(entry["id"])
                if target.role in (Role.merlin, Role.morgana):
                    entry["alignment_hint"] = "merlin_candidate"
            return visibility

        return visibility

    def token_for(self, player_id: str) -> str:
        token = self._token_by_player_id.get(player_id)
        if not token:
            raise ValueError("未知玩家")
        return token

    def host_token(self) -> str:
        if not self._host_token:
            raise ValueError("主机令牌未初始化")
        return self._host_token

    def is_host_token(self, token: Optional[str]) -> bool:
        return bool(token and self._host_token and token == self._host_token)

    def player_id_for_token(self, token: str) -> str:
        player_id = self._player_id_by_token.get(token)
        if not player_id:
            raise ValueError("无效的玩家令牌")
        return player_id

    def _emit(self, event_type: str, payload: Dict[str, Any]) -> None:
        self._store.append(Event(type=event_type, payload=payload))

    def _has_player(self, player_id: str) -> bool:
        return any(p.id == player_id for p in self.state.players)

    def _get_player(self, player_id: str) -> Player:
        for p in self.state.players:
            if p.id == player_id:
                return p
        raise ValueError("未知玩家")

    def _next_id(self, prefix: str) -> str:
        existing = [p.id for p in self.state.players if p.id.startswith(prefix)]
        numbers = []
        for pid in existing:
            try:
                numbers.append(int(pid[1:]))
            except ValueError:
                continue
        next_num = max(numbers, default=0) + 1
        return f"{prefix}{next_num}"

    @staticmethod
    def _clean_name(name: str) -> str:
        cleaned = name.strip()
        if not cleaned:
            raise ValueError("名字不能为空")
        if len(cleaned) > MAX_NAME_LENGTH:
            raise ValueError(f"名字过长（最多 {MAX_NAME_LENGTH} 个字符）")
        return cleaned

    def _assign_token(self, player_id: str) -> None:
        token = str(uuid.uuid4())
        self._token_by_player_id[player_id] = token
        self._player_id_by_token[token] = player_id

    def _clear_token(self, player_id: str) -> None:
        token = self._token_by_player_id.pop(player_id, None)
        if token:
            self._player_id_by_token.pop(token, None)

    def _rotate_token(self, player_id: str) -> None:
        self._clear_token(player_id)
        self._assign_token(player_id)
