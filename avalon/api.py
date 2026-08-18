from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .bot.manager import BotManager
from .bot.prompts import build_action_instructions, build_context, build_system_prompt
from .config import SETTINGS
from .game import GameEngine, GameNotCreatedError
from .models import (
    ActionRequest,
    CreateGameRequest,
    Event,
    Phase,
    PlayerAddRequest,
    PlayerJoinRequest,
    PlayerReadyRequest,
    PlayerUpdateRequest,
)
from .storage import EventStore
from .tunnel import TunnelManager

logger = logging.getLogger("avalon")
DEBUG_LOGS = os.getenv("AVALON_DEBUG", "").lower() in {"1", "true", "yes"}

# Admin token: sha256 hash of the admin password. Empty string means admin auth is disabled.
_admin_token_hash = hashlib.sha256(SETTINGS.admin_password.encode()).hexdigest() if SETTINGS.admin_password else ""


def log_event(event: str, **fields: object) -> None:
    if not DEBUG_LOGS:
        return
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=True))


# Headers added by reverse proxies and tunnel daemons (e.g. cloudflared).
PROXY_HEADERS = ("cf-connecting-ip", "x-forwarded-for", "x-real-ip", "forwarded")


def is_local_request(request: Request) -> bool:
    """True only for requests that genuinely originate on this machine.

    Tunnel daemons such as cloudflared connect from loopback, so checking the
    client host alone would treat every remote player as local. Proxied
    requests carry forwarding headers; their presence marks the request remote.
    """
    if not request.client or request.client.host not in ("127.0.0.1", "::1"):
        return False
    return not any(header in request.headers for header in PROXY_HEADERS)


def is_admin(request: Request, admin_token: Optional[str] = None) -> bool:
    """True if the request is from localhost OR carries a valid admin token.

    When AVALON_ADMIN_PASSWORD is not set, falls back to localhost-only access
    (original behavior).
    """
    if is_local_request(request):
        return True
    if not _admin_token_hash:
        return False
    return admin_token == _admin_token_hash


if DEBUG_LOGS:
    logging.basicConfig(level=logging.INFO)


store = EventStore(SETTINGS.database_path)
engine = GameEngine(store)
bot_manager = BotManager(engine)
tunnel_manager = TunnelManager(f"http://localhost:{SETTINGS.port}")


async def _bot_loop() -> None:
    while True:
        try:
            if engine.has_state():
                await bot_manager.maybe_act()
        except Exception as exc:  # pragma: no cover - best-effort background loop
            log_event("bot_loop_error", error=str(exc))
        await asyncio.sleep(0.5)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    bot_task = asyncio.create_task(_bot_loop())
    try:
        yield
    finally:
        bot_task.cancel()


app = FastAPI(title="Avalon", lifespan=lifespan)
WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB_DIR / "control.html")


@app.get("/control")
async def control() -> FileResponse:
    return FileResponse(WEB_DIR / "control.html")


@app.get("/play")
async def play() -> FileResponse:
    return FileResponse(WEB_DIR / "lobby.html")


@app.get("/game")
async def game() -> FileResponse:
    return FileResponse(WEB_DIR / "game.html")


@app.get("/lobby")
async def lobby() -> FileResponse:
    return FileResponse(WEB_DIR / "lobby.html")


@app.get("/admin/status")
async def admin_status() -> Dict[str, Any]:
    """Return whether admin auth is required (AVALON_ADMIN_PASSWORD is set)."""
    return {"admin_required": bool(_admin_token_hash)}


@app.post("/admin/login")
async def admin_login(body: Dict[str, str]) -> Dict[str, Any]:
    """Validate admin password and return admin_token."""
    if not _admin_token_hash:
        raise HTTPException(status_code=400, detail="未设置管理员密码")
    password = body.get("password", "")
    if not password:
        raise HTTPException(status_code=400, detail="密码不能为空")
    token = hashlib.sha256(password.encode()).hexdigest()
    if token != _admin_token_hash:
        raise HTTPException(status_code=403, detail="密码错误")
    return {"admin_token": token}


@app.post("/game/new")
async def new_game(req: CreateGameRequest, request: Request) -> Dict[str, Any]:
    if not is_admin(request, req.admin_token):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    state = await engine.create_game(req)
    log_event(
        "game_created",
        game_id=state.id,
        player_count=len(state.players),
        bot_count=sum(1 for p in state.players if p.is_bot),
        lady_of_lake=state.config.lady_of_lake,
    )
    return {"state": engine.public_state(), "host_token": engine.host_token()}


@app.post("/game/start")
async def start_game(request: Request, admin_token: Optional[str] = None) -> Dict[str, Any]:
    if not is_admin(request, admin_token):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    state = await engine.start_game()
    log_event("game_started", game_id=state.id, player_count=len(state.players))
    await bot_manager.maybe_act()
    return {"state": engine.public_state()}


@app.post("/game/action")
async def action(req: ActionRequest, request: Request) -> Dict[str, Any]:
    player_id = req.player_id
    if req.token:
        player_id = engine.player_id_for_token(req.token)
    if not player_id:
        raise HTTPException(status_code=400, detail="需要令牌")
    if not req.token and not is_local_request(request):
        raise HTTPException(status_code=403, detail="需要令牌")
    log_event("player_action", player_id=player_id, action_type=req.action_type)
    await engine.apply_action(player_id, req.action_type, req.payload)
    await bot_manager.maybe_act()
    return {"state": engine.public_state()}


@app.get("/game/state")
async def get_state(
    request: Request, player_id: Optional[str] = None, token: Optional[str] = None
) -> Dict[str, Any]:
    if not engine.has_state():
        return {"state": None}
    pending_humans, pending_bots = engine.pending_actions()
    pending = {"human": pending_humans, "bot": pending_bots}
    if token:
        player_id = engine.player_id_for_token(token)
    if player_id:
        if not token and not is_local_request(request):
            raise HTTPException(status_code=403, detail="需要令牌")
        payload = engine.private_state_for(player_id)
        payload["player_id"] = player_id
        payload["pending"] = pending
        return payload
    return {"state": engine.public_state(), "pending": pending}


@app.get("/game/host_token")
async def get_host_token(request: Request, admin_token: Optional[str] = None) -> Dict[str, Any]:
    if not is_admin(request, admin_token):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    return {"host_token": engine.host_token()}


# Ballot resolution events; until one lands, team votes stay hidden.
TEAM_VOTE_RESOLUTIONS = {"team_approved", "team_rejected", "team_hammered"}


def public_events() -> List[Event]:
    """Event log with secret ballots removed.

    Quest votes never leave the server (only aggregate fail counts are public).
    Team votes are withheld until their proposal resolves so nobody can watch
    ballots land before casting their own.
    """
    visible: List[Event] = []
    open_ballots: List[Event] = []
    for event in store.list_events():
        if event.type == "quest_vote":
            continue
        if event.type == "team_proposed":
            open_ballots = []
            visible.append(event)
        elif event.type == "team_vote":
            open_ballots.append(event)
        elif event.type in TEAM_VOTE_RESOLUTIONS:
            visible.extend(open_ballots)
            open_ballots = []
            visible.append(event)
        else:
            visible.append(event)
    return visible


@app.get("/game/events")
async def get_events() -> Dict[str, Any]:
    return {"events": public_events()}


@app.get("/game/pending_bots")
async def pending_bots(request: Request) -> Dict[str, Any]:
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    if not engine.has_state():
        return {"pending_bots": [], "phase": None, "game_over": False, "winner": None}
    state = engine.state
    _, bot_pending = engine.pending_actions()
    return {
        "pending_bots": bot_pending,
        "phase": state.phase.value,
        "game_over": state.phase == Phase.game_over,
        "winner": state.winner.value if state.winner else None,
    }


@app.get("/game/bot_context/{bot_id}")
async def bot_context(bot_id: str, request: Request) -> Dict[str, Any]:
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    if SETTINGS.bot_mode != "external":
        raise HTTPException(status_code=400, detail="未启用外部机器人模式")
    if not engine.has_state():
        raise HTTPException(status_code=400, detail="没有进行中的游戏")
    state = engine.state
    player = next((p for p in state.players if p.id == bot_id), None)
    if not player:
        raise HTTPException(status_code=404, detail="未知玩家")
    if not player.is_bot:
        raise HTTPException(status_code=400, detail="不是机器人")
    _, bot_pending = engine.pending_actions()
    if bot_id not in bot_pending:
        raise HTTPException(status_code=400, detail="此机器人没有待处理的操作")

    knowledge = engine.knowledge_for(bot_id)
    id_to_name = {p.id: p.name for p in state.players}
    recent_chat = [
        f"{id_to_name.get(msg.player_id, msg.player_id)}: {msg.message}"
        for msg in state.chat[-SETTINGS.max_recent_chat:]
    ]
    system = build_system_prompt(player, knowledge)
    context = build_context(state, bot_id, recent_chat)
    instructions = build_action_instructions(state, player)
    full_prompt = f"{system}\n\n{context}\n\n{instructions}"

    player_names = [p.name for p in state.players]
    name_to_id = {p.name: p.id for p in state.players}

    return {
        "bot_id": bot_id,
        "bot_name": player.name,
        "role": player.role.value if player.role else None,
        "phase": state.phase.value,
        "full_prompt": full_prompt,
        "player_names": player_names,
        "name_to_id": name_to_id,
    }


@app.post("/game/players/add")
async def add_player(req: PlayerAddRequest, request: Request) -> Dict[str, Any]:
    if not engine.is_host_token(req.host_token) and not is_local_request(request):
        raise HTTPException(status_code=403, detail="需要主机令牌")
    state = await engine.add_player(req.is_bot, req.name)
    log_event(
        "player_added",
        game_id=state.id,
        player_id=state.players[-1].id if state.players else None,
        is_bot=req.is_bot,
    )
    return {"state": engine.public_state()}


@app.post("/game/players/remove")
async def remove_player(req: PlayerUpdateRequest, request: Request) -> Dict[str, Any]:
    if not engine.is_host_token(req.host_token) and not is_local_request(request):
        raise HTTPException(status_code=403, detail="需要主机令牌")
    state = await engine.remove_player(req.player_id)
    log_event("player_removed", game_id=state.id, player_id=req.player_id)
    return {"state": engine.public_state()}


@app.post("/game/players/remove_last_human")
async def remove_last_human(request: Request, host_token: Optional[str] = None) -> Dict[str, Any]:
    if not engine.is_host_token(host_token) and not is_local_request(request):
        raise HTTPException(status_code=403, detail="需要主机令牌")
    state = await engine.remove_last_human_slot()
    log_event("human_slot_removed", game_id=state.id)
    return {"state": engine.public_state()}


@app.post("/game/players/rename")
async def rename_player(req: PlayerUpdateRequest, request: Request) -> Dict[str, Any]:
    is_localhost = is_local_request(request)
    is_host = engine.is_host_token(req.host_token)
    # Allow self-rename if player provides their own valid token
    is_self_rename = False
    if req.token:
        try:
            token_player_id = engine.player_id_for_token(req.token)
            is_self_rename = token_player_id == req.player_id
        except ValueError:
            pass
    if not is_localhost and not is_host and not is_self_rename:
        raise HTTPException(status_code=403, detail="无权重命名此玩家")
    if not req.name:
        raise HTTPException(status_code=400, detail="名字不能为空")
    state = await engine.rename_player(req.player_id, req.name)
    log_event("player_renamed", game_id=state.id, player_id=req.player_id, name=req.name)
    return {"state": engine.public_state()}


@app.post("/game/players/reset")
async def reset_player(req: PlayerUpdateRequest, request: Request) -> Dict[str, Any]:
    if not engine.is_host_token(req.host_token) and not is_local_request(request):
        raise HTTPException(status_code=403, detail="需要主机令牌")
    state = await engine.reset_player(req.player_id)
    log_event("player_reset", game_id=state.id, player_id=req.player_id)
    return {"state": engine.public_state()}


@app.post("/game/players/join")
async def join_player(req: PlayerJoinRequest) -> Dict[str, Any]:
    if not req.name:
        raise HTTPException(status_code=400, detail="名字不能为空")
    player = await engine.join_next_human(req.name)
    token = engine.token_for(player.id)
    log_event("player_joined", player_id=player.id, name=player.name, is_bot=player.is_bot)
    return {"player_id": player.id, "token": token, "state": engine.public_state()}


@app.post("/game/players/ready")
async def ready_player(req: PlayerReadyRequest, request: Request) -> Dict[str, Any]:
    player_id = req.player_id
    if req.token:
        player_id = engine.player_id_for_token(req.token)
    if not player_id:
        raise HTTPException(status_code=400, detail="需要令牌")
    if not req.token and not is_local_request(request):
        raise HTTPException(status_code=403, detail="需要令牌")
    state = await engine.set_ready(player_id, req.ready)
    log_event(
        "player_ready",
        game_id=state.id,
        player_id=player_id,
        ready=req.ready,
        started=state.started,
    )
    humans = [p for p in state.players if not p.is_bot]
    all_ready = humans and all(p.claimed and p.ready for p in humans)
    if not state.started and all_ready:
        state = await engine.start_game()
        log_event("game_auto_started", game_id=state.id, player_count=len(state.players))
        await bot_manager.maybe_act()
    return {"state": engine.public_state()}


@app.post("/tunnel/start")
async def start_tunnel(request: Request) -> Dict[str, Any]:
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    status = tunnel_manager.start()
    return {"tunnel": status.__dict__}


@app.get("/tunnel/status")
async def tunnel_status(request: Request) -> Dict[str, Any]:
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    status = tunnel_manager.status()
    return {"tunnel": status.__dict__}


@app.post("/tunnel/stop")
async def stop_tunnel(request: Request) -> Dict[str, Any]:
    if not is_local_request(request):
        raise HTTPException(status_code=403, detail="仅限本地访问")
    status = tunnel_manager.stop()
    return {"tunnel": status.__dict__}


@app.websocket("/game/stream")
async def stream_state(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            payload = None if not engine.has_state() else engine.public_state().model_dump()
            await websocket.send_json({"type": "state", "payload": payload})
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        return


@app.exception_handler(GameNotCreatedError)
async def game_not_created_handler(_: Request, exc: GameNotCreatedError) -> JSONResponse:
    # Routes that touch engine.state before /game/new reach this. Without it the
    # bare RuntimeError would escape as a plain-text 500 (not the {"error": ...}
    # JSON the web clients read via body.error). Treated as a 400 precondition
    # failure, consistent with the engine's other "wrong game state" ValueErrors
    # (e.g. "Game not started"). Registered for this subclass only, so an
    # unexpected RuntimeError elsewhere still surfaces as a 500.
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(ValueError)
async def value_error_handler(_: Request, exc: ValueError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": str(exc)})


@app.exception_handler(HTTPException)
async def http_exception_handler(_: Request, exc: HTTPException) -> JSONResponse:
    # Route handlers raise HTTPException for auth/validation failures; clients
    # read the error from {"error": ...}, so reshape FastAPI's default
    # {"detail": ...} body to match (mirrors value_error_handler above).
    return JSONResponse(status_code=exc.status_code, content={"error": exc.detail})
