# Architecture

Single-process FastAPI app hosting one Avalon game at a time, played by humans
(local browser or remote via tunnel) and bots (heuristic or LLM).

## Components

- `avalon/api.py` — HTTP/WebSocket surface. Owns the module-level singletons:
  `EventStore`, `GameEngine`, `BotManager`, `TunnelManager`. A lifespan task polls
  `BotManager.maybe_act()` every 0.5s so bots catch up whenever no human action is pending.
  Route guards signal auth/validation failures by raising `HTTPException`; exception
  handlers reshape it, engine `ValueError`s, and `GameNotCreatedError` (an action that
  needs an active game arriving before `/game/new`) to `{"error": ...}` JSON (the shape
  the web clients read), all as 400s. `GameNotCreatedError` is handled by its own
  (`RuntimeError`-subclass) type so that path returns a clean 400 instead of a bare 500
  while any *unexpected* `RuntimeError` still surfaces as a 500. FastAPI's own
  routing/validation errors (404/422) are untouched.
- `avalon/game.py` — rules engine. Pure-ish state machine over `GameState`
  (`avalon/models.py`): proposals, team votes, quests, Lady of the Lake, assassination,
  hammer and five-rejection rules. Emits events to the store; guarded by an asyncio lock.
  It is also the input-validation boundary: rosters must be 5–10 players with unique,
  non-empty IDs, and untrusted free text (chat messages, player names) is length-capped
  (`MAX_CHAT_LENGTH`, `MAX_NAME_LENGTH`) since it is echoed into every deep-copied snapshot.
  Ballots are committed on first cast: a resubmitted team vote or quest card is ignored
  (a double-click can't flip a committed vote, double-count toward resolution, or emit a
  second ballot event), mirroring Avalon's simultaneous, final reveal. The other actions
  are already single-shot — proposing, peeking, and assassinating each leave their phase.
- `avalon/storage.py` — append-only SQLite event log (replay/debug). Supports `:memory:`
  (kept on one connection) for tests.
- `avalon/bot/` — `manager.py` drives pending bots; `policy.py` decides actions
  (LLM with validation/retry via `llm.py`, falling back to heuristics); `prompts.py`
  builds the LLM context. Bots receive no secret ballot data.
- `avalon/tunnel.py` — optional cloudflared quick-tunnel for remote players.
- `avalon/web/` — static frontend (control panel, lobby, game view) polling
  `/game/state` and `/game/events`. This is the **output-encoding boundary**:
  player names are attacker-controlled (any remote player names themselves) and
  the server stores/serves them verbatim, so the frontend must render names with
  `textContent` (or DOM nodes), never by interpolating them into `innerHTML`.
  The host renders these names in a localhost-privileged page, so an unescaped
  name is a stored-XSS → privilege-escalation vector.

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
- **End-game reveal:** once `phase == game_over` the hidden-role veil lifts — roles and the
  full Lady history become public in every snapshot (the tabletop end-of-game flip).
  Individual quest ballots stay secret even then, mirroring the shuffled physical quest
  cards; they are also already empty by game over (cleared as each quest resolves). This
  is safe because `game_over` is terminal: no decision depends on the now-public roles.
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
full bot games, storage, the Lady of the Lake flow (timing, holder knowledge, token
passing, the no-repeat-holder rule), the LLM-output parsing layer (`LLMClient.extract_*`
and name resolution), and the per-role/per-phase prompt builders. `tests/conftest.py`
forces heuristic mode and a temp DB before `avalon.config` is imported, so no model is
ever loaded.

`tests/test_typing.py` runs `mypy avalon` as a regression gate: pyproject sets
`[tool.mypy] strict = true`, and the package is kept clean under it (the test skips
when mypy is not installed).
