# Architecture

Single-process FastAPI app hosting one Avalon game at a time, played by humans
(local browser or remote via tunnel) and bots (heuristic or LLM).

## Components

- `avalon/api.py` — HTTP/WebSocket surface. Owns the module-level singletons:
  `EventStore`, `GameEngine`, `BotManager`, `TunnelManager`. A lifespan task polls
  `BotManager.maybe_act()` every 0.5s so bots catch up whenever no human action is pending.
- `avalon/game.py` — rules engine. Pure-ish state machine over `GameState`
  (`avalon/models.py`): proposals, team votes, quests, Lady of the Lake, assassination,
  hammer and five-rejection rules. Emits events to the store; guarded by an asyncio lock.
- `avalon/storage.py` — append-only SQLite event log (replay/debug). Supports `:memory:`
  (kept on one connection) for tests.
- `avalon/bot/` — `manager.py` drives pending bots; `policy.py` decides actions
  (LLM with validation/retry via `llm.py`, falling back to heuristics); `prompts.py`
  builds the LLM context. Bots receive no secret ballot data.
- `avalon/tunnel.py` — optional cloudflared quick-tunnel for remote players.
- `avalon/web/` — static frontend (control panel, lobby, game view) polling
  `/game/state` and `/game/events`.

## Access tiers

1. **Genuine localhost** — full control (create/start games, host token, tunnel control,
   bot context). `is_local_request` requires a loopback peer *and* no forwarding headers,
   so tunneled requests (cloudflared connects from 127.0.0.1) do not count.
2. **Host token** — player management from anywhere (returned by `/game/new`).
3. **Player token** — per-player UUID minted at seat assignment; authorizes actions and
   the private state view (`/game/state?token=...`).

## Information hiding

- `GameEngine.public_state(viewer_id)` strips roles and Lady history, hides open team
  votes (only the viewer's own ballot) until the proposal resolves, and never exposes
  individual quest votes — only aggregate fail counts after resolution.
- `public_events()` in `api.py` applies the same policy to the event log: `quest_vote`
  events are dropped; `team_vote` events are withheld until their resolution event.
- Role knowledge (Merlin's sight, evil mutual knowledge, Percival's candidates) is
  computed per player in `GameEngine` and served only through the private state view.

## Bot modes (`AVALON_BOT_MODE`)

- `heuristic` — silent rule-based decisions, no LLM. Used by the test suite.
- `llm` — local MLX model (`QWEN_MODEL`) with format extraction, retry, and heuristic
  fallback. A bot assassin with a human evil teammate defers once and follows a chat
  message that names exactly one viable target.
- `external` — internal loop disabled; an orchestrator polls `/game/pending_bots`,
  fetches `/game/bot_context/{bot_id}` (localhost only), and submits via `/game/action`.

## Tests

`tests/` runs against the working tree (editable install): rules engine, ballot secrecy
(engine and HTTP), localhost/proxy detection, token auth, bot deferral/no-spam loop,
full bot games, and storage. `tests/conftest.py` forces heuristic mode and a temp DB
before `avalon.config` is imported.
