from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class Alignment(str, Enum):
    loyal = "loyal"
    evil = "evil"


class Phase(str, Enum):
    lobby = "lobby"
    team_proposal = "team_proposal"
    team_vote = "team_vote"
    quest = "quest"
    lady_of_lake = "lady_of_lake"
    assassination = "assassination"
    game_over = "game_over"


class Role(str, Enum):
    merlin = "Merlin"
    percival = "Percival"
    loyal_servant = "Loyal Servant"
    assassin = "Assassin"
    morgana = "Morgana"
    mordred = "Mordred"
    oberon = "Oberon"
    minion = "Minion of Mordred"


class Player(BaseModel):
    id: str
    name: str
    is_bot: bool = False
    role: Optional[Role] = None
    claimed: bool = False
    ready: bool = False


class ChatMessage(BaseModel):
    player_id: str
    message: str


class QuestRecord(BaseModel):
    quest_number: int
    team: List[str]
    fails: int
    succeeded: bool


class GameConfig(BaseModel):
    player_count: int
    roles: List[Role]
    hammer_auto_approve: bool = True
    lady_of_lake: bool = False


class GameState(BaseModel):
    id: str
    config: GameConfig
    players: List[Player]
    started: bool = False
    phase: Phase = Phase.lobby
    leader_index: int = 0
    quest_number: int = 1
    proposal_attempts: int = 0
    proposed_team: List[str] = Field(default_factory=list)
    team_votes: Dict[str, bool] = Field(default_factory=dict)
    quest_votes: Dict[str, bool] = Field(default_factory=dict)
    quest_history: List[QuestRecord] = Field(default_factory=list)
    success_count: int = 0
    fail_count: int = 0
    winner: Optional[Alignment] = None
    assassin_target: Optional[str] = None
    chat: List[ChatMessage] = Field(default_factory=list)
    lady_holder_id: Optional[str] = None
    lady_last_used_quest: Optional[int] = None
    lady_history: List[Dict[str, str]] = Field(default_factory=list)


class Event(BaseModel):
    type: str
    payload: Dict[str, Any]


class CreateGameRequest(BaseModel):
    players: List[Player]
    roles: Optional[List[Role]] = None
    hammer_auto_approve: bool = True
    lady_of_lake: bool = True


class ActionRequest(BaseModel):
    player_id: Optional[str] = None
    token: Optional[str] = None
    action_type: str
    payload: Dict[str, Any] = Field(default_factory=dict)


class PlayerUpdateRequest(BaseModel):
    player_id: str
    name: Optional[str] = None
    host_token: Optional[str] = None
    token: Optional[str] = None  # Player's own token for self-rename


class PlayerAddRequest(BaseModel):
    is_bot: bool = False
    name: Optional[str] = None
    host_token: Optional[str] = None


class PlayerJoinRequest(BaseModel):
    name: str


class PlayerReadyRequest(BaseModel):
    player_id: Optional[str] = None
    token: Optional[str] = None
    ready: bool = True
