from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Dict, Optional

from pathlib import Path

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .bot.manager import BotManager
from .bot.prompts import build_action_instructions, build_context, build_system_prompt
from .config import SETTINGS
from .game import GameEngine
from .models import (
    ActionRequest,
    CreateGameRequest,
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


def log_event(event: str, **fields: object) -> None:
    if not DEBUG_LOGS:
        return
    payload = {"event": event, **fields}
    logger.info(json.dumps(payload, ensure_ascii=True))


if DEBUG_LOGS:
    logging.basicConfig(level=logging.INFO)


store = EventStore(SETTINGS.database_path)
engine = GameEngine(store)
bot_manager = BotManager(engine)
tunnel_manager = TunnelManager(f"http://localhost:{SETTINGS.port}")

app = FastAPI(title="Avalon")
WEB_DIR = Path(__file__).parent / "web"
app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.on_event("startup")
async def start_bot_loop() -> None:
    async def bot_loop() -> None:
        while True:
            try:
                if engine.has_state():
                    await bot_manager.maybe_act()
            except Exception as exc:  # pragma: no cover - best-effort background loop
                log_event("bot_loop_error", error=str(exc))
            await asyncio.sleep(0.5)

    asyncio.create_task(bot_loop())


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


@app.post("/game/new")
async def new_game(req: CreateGameRequest) -> Dict:
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
async def start_game() -> Dict:
    state = await engine.start_game()
    log_event("game_started", game_id=state.id, player_count=len(state.players))
    await bot_manager.maybe_act()
    return {"state": engine.public_state()}


@app.post("/game/action")
async def action(req: ActionRequest, request: Request) -> Dict:
    player_id = req.player_id
    if req.token:
        player_id = engine.player_id_for_token(req.token)
    if not player_id:
        return JSONResponse(status_code=400, content={"error": "token required"})
    if not req.token and request.client and request.client.host not in ("127.0.0.1", "::1"):
        return JSONResponse(status_code=403, content={"error": "token required"})
    log_event("player_action", player_id=player_id, action_type=req.action_type)
    await engine.apply_action(player_id, req.action_type, req.payload)
    await bot_manager.maybe_act()
    return {"state": engine.public_state()}


@app.get("/game/state")
async def get_state(
    request: Request, player_id: Optional[str] = None, token: Optional[str] = None
) -> Dict:
    if not engine.has_state():
        return {"state": None}
    pending_humans, pending_bots = engine.pending_actions()
    pending = {"human": pending_humans, "bot": pending_bots}
    if token:
        player_id = engine.player_id_for_token(token)
    if player_id:
        if not token and request.client and request.client.host not in ("127.0.0.1", "::1"):
            return JSONResponse(status_code=403, content={"error": "token required"})
        payload = engine.private_state_for(player_id)
        payload["player_id"] = player_id
        payload["pending"] = pending
        return payload
    return {"state": engine.public_state(), "pending": pending}


@app.get("/game/host_token")
async def get_host_token(request: Request) -> Dict:
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        return JSONResponse(status_code=403, content={"error": "localhost only"})
    return {"host_token": engine.host_token()}


@app.get("/game/events")
async def get_events() -> Dict:
    return {"events": store.list_events()}


@app.get("/game/pending_bots")
async def pending_bots(request: Request) -> Dict:
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        return JSONResponse(status_code=403, content={"error": "localhost only"})
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
async def bot_context(bot_id: str, request: Request) -> Dict:
    if request.client and request.client.host not in ("127.0.0.1", "::1"):
        return JSONResponse(status_code=403, content={"error": "localhost only"})
    if SETTINGS.bot_mode != "external":
        return JSONResponse(status_code=400, content={"error": "external bot mode not enabled"})
    if not engine.has_state():
        return JSONResponse(status_code=400, content={"error": "no active game"})
    state = engine.state
    player = next((p for p in state.players if p.id == bot_id), None)
    if not player:
        return JSONResponse(status_code=404, content={"error": "unknown player"})
    if not player.is_bot:
        return JSONResponse(status_code=400, content={"error": "not a bot"})
    _, bot_pending = engine.pending_actions()
    if bot_id not in bot_pending:
        return JSONResponse(status_code=400, content={"error": "no pending action for this bot"})

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
async def add_player(req: PlayerAddRequest, request: Request) -> Dict:
    if (
        not engine.is_host_token(req.host_token)
        and request.client
        and request.client.host not in ("127.0.0.1", "::1")
    ):
        return JSONResponse(status_code=403, content={"error": "host token required"})
    state = await engine.add_player(req.is_bot, req.name)
    log_event(
        "player_added",
        game_id=state.id,
        player_id=state.players[-1].id if state.players else None,
        is_bot=req.is_bot,
    )
    return {"state": engine.public_state()}


@app.post("/game/players/remove")
async def remove_player(req: PlayerUpdateRequest, request: Request) -> Dict:
    if (
        not engine.is_host_token(req.host_token)
        and request.client
        and request.client.host not in ("127.0.0.1", "::1")
    ):
        return JSONResponse(status_code=403, content={"error": "host token required"})
    state = await engine.remove_player(req.player_id)
    log_event("player_removed", game_id=state.id, player_id=req.player_id)
    return {"state": engine.public_state()}


@app.post("/game/players/remove_last_human")
async def remove_last_human(request: Request, host_token: Optional[str] = None) -> Dict:
    if (
        not engine.is_host_token(host_token)
        and request.client
        and request.client.host not in ("127.0.0.1", "::1")
    ):
        return JSONResponse(status_code=403, content={"error": "host token required"})
    state = await engine.remove_last_human_slot()
    log_event("human_slot_removed", game_id=state.id)
    return {"state": engine.public_state()}


@app.post("/game/players/rename")
async def rename_player(req: PlayerUpdateRequest, request: Request) -> Dict:
    is_localhost = request.client and request.client.host in ("127.0.0.1", "::1")
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
        return JSONResponse(status_code=403, content={"error": "Not authorized to rename this player"})
    if not req.name:
        return JSONResponse(status_code=400, content={"error": "Name required"})
    state = await engine.rename_player(req.player_id, req.name)
    log_event("player_renamed", game_id=state.id, player_id=req.player_id, name=req.name)
    return {"state": engine.public_state()}


@app.post("/game/players/reset")
async def reset_player(req: PlayerUpdateRequest, request: Request) -> Dict:
    if (
        not engine.is_host_token(req.host_token)
        and request.client
        and request.client.host not in ("127.0.0.1", "::1")
    ):
        return JSONResponse(status_code=403, content={"error": "host token required"})
    state = await engine.reset_player(req.player_id)
    log_event("player_reset", game_id=state.id, player_id=req.player_id)
    return {"state": engine.public_state()}


@app.post("/game/players/claim")
async def claim_player(req: PlayerUpdateRequest) -> Dict:
    if not req.name:
        return JSONResponse(status_code=400, content={"error": "Name required"})
    state = await engine.claim_player(req.player_id, req.name)
    return {"state": engine.public_state()}


@app.post("/game/players/join")
async def join_player(req: PlayerJoinRequest) -> Dict:
    if not req.name:
        return JSONResponse(status_code=400, content={"error": "Name required"})
    player = await engine.join_next_human(req.name)
    token = engine.token_for(player.id)
    log_event("player_joined", player_id=player.id, name=player.name, is_bot=player.is_bot)
    return {"player_id": player.id, "token": token, "state": engine.public_state()}


@app.post("/game/players/ready")
async def ready_player(req: PlayerReadyRequest, request: Request) -> Dict:
    player_id = req.player_id
    if req.token:
        player_id = engine.player_id_for_token(req.token)
    if not player_id:
        return JSONResponse(status_code=400, content={"error": "token required"})
    if not req.token and request.client and request.client.host not in ("127.0.0.1", "::1"):
        return JSONResponse(status_code=403, content={"error": "token required"})
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
async def start_tunnel() -> Dict:
    status = tunnel_manager.start()
    return {"tunnel": status.__dict__}


@app.get("/tunnel/status")
async def tunnel_status() -> Dict:
    status = tunnel_manager.status()
    return {"tunnel": status.__dict__}


@app.post("/tunnel/stop")
async def stop_tunnel() -> Dict:
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


@app.exception_handler(ValueError)
async def value_error_handler(_, exc: ValueError):
    return JSONResponse(status_code=400, content={"error": str(exc)})
