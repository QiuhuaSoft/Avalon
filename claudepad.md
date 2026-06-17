# Claudepad - Avalon Session Memory

## Session Summaries

### 2026-06-17T~UTC - Type-safety pass: made package mypy --strict clean (75 -> 0)
- pyproject declared `[tool.mypy] strict = true` but `mypy avalon` reported **75 errors** —
  the config was never honored. Drove it to **0 errors** across all 13 modules.
- Mechanical bulk: widened bare `Dict` -> `Dict[str, Any]` on every engine handler/payload,
  bot-policy decision return, and visibility builder; added `mlx_lm.*` ignore-missing-imports
  override (the lib ships no stubs); typed `LLMClient.generate`'s local and the `value_error`
  handler. Wrapped the now-too-long signatures to stay ruff-clean (line-length 100).
- Real fix surfaced by the type errors: `alignment_for(None)` silently returned
  `Alignment.loyal`. Converted to `@overload`s returning `Optional[Alignment]` so a role-less
  player maps to `None`, not "good". All call sites verified safe (every `.value` is role-guarded;
  comparisons only flip in states unreachable before roles are assigned). Latent, but a footgun.
- api.py refactor: ~26 `return JSONResponse(status_code=N, content={"error": M})` guards became
  idiomatic `raise HTTPException(N, M)`, with a new `@app.exception_handler(HTTPException)` that
  reshapes back to `{"error": ...}` (the shape `web/*.js` read via `body.error`). Keyed on
  `fastapi.HTTPException`, so Starlette's 404/405 and 422 validation bodies are untouched.
- Removed dead `Phase.quest_result` (never set/read anywhere).
- Tests 97 -> 100: `alignment_for` mapping incl. None; auth-error JSON shape; and
  `tests/test_typing.py` runs `mypy avalon` as a regression gate (subprocess, skips if absent).
- Verified: ruff clean, mypy clean, 100 pass in ~0.5s. Wet-tested a real all-bot heuristic game
  to game_over (5 quests, Lady fired 3x, no `quest_vote` leaked); live error paths return the
  right status+shape and 404 still `{"detail":...}`. Two parallel code-review agents: no findings.

### 2026-06-17T~UTC - Hardening pass: fixed LLM-parser bug, assassin guard, +57 tests
- Found and fixed a real parsing bug: `LLMClient.extract_team/extract_say/extract_target`
  used `\s*` after the keyword, which matches newlines — an empty `TEAM:`/`SAY:`/`TARGET:`
  line silently captured the *next* line (e.g. a trailing `SAY:`). Switched to `[^\S\n]*`
  (horizontal whitespace only) so a field never reaches across a line break.
- Engine hardening: the assassin can no longer target themselves or a known evil teammate
  (both auto-forfeit the game). Oberon is deliberately NOT guarded — the assassin can't tell
  Oberon from a good player, so rejecting that shot would leak Oberon's alignment.
- Frontend: the assassination dropdown now hides the assassin + known-evil teammates (uses the
  private `visibility` data; Oberon stays listed). Mirrors the engine guard. Syntax-checked.
- Tests grew 40 -> 97: new `test_llm_extraction.py` (parsing layer + name resolution),
  `test_prompts.py` (every role/phase), `test_lady_of_lake.py` (timing, holder knowledge,
  token passing, recurrence before quests 3/4), plus assassin self/teammate/Oberon engine cases.
  `started_engine` now seeds the Lady holder like real `start_game`.
- Cleaned all 12 ruff errors in `scripts/` (import order + line length). Whole repo is ruff-clean;
  pytest green in ~0.25s. Wet-tested: booted a local server, all-bot game ran to game_over, no
  `quest_vote` leaked into the public event log.

### 2026-06-11T~UTC - Landed WIP (secrecy + hardening) and added the test suite
- Finished and committed the in-progress batch: `is_local_request` proxy-header hardening
  (tunneled requests no longer count as localhost), ballot secrecy (`public_state(viewer_id)`
  redaction + `public_events()` filter), official 8/9/10-player role sets, five-rejection rule,
  bot-assassin deferral to human evil teammates (no chat spam, follows single-name guidance),
  EventStore `:memory:` support + tz-aware timestamps.
- Wrote the first test suite: 40 tests in `tests/` (engine rules, API auth/secrecy via
  TestClient with spoofed client addresses, bot policy/manager, storage). `pytest` runs in ~0.3s.
- Replaced deprecated `@app.on_event("startup")` with a lifespan handler (bot loop now
  cancelled on shutdown). Repo is now ruff-clean; added `[tool.pytest.ini_options]`.
- Wet-tested: booted a real server, all-bot game completed in ~4s, proxied host_token 403'd.
- Added ARCHITECTURE.md; fixed stale docs (README said 7 players max; CLAUDE.md pointed at a
  nonexistent smoke_test.py — real script is scripts/smoke_game.sh).

### 2026-02-12T~20:00Z - External Bot Mode Implementation + Full Game Test
- Implemented external bot mode: `manager.py` early return + two new API endpoints (`/game/pending_bots`, `/game/bot_context/{bot_id}`)
- Ran a full 5-player game (1 human Merlin + 4 Opus sub-agent bots)
- Game result: Good won 3-0 quests, but Assassin (Dave) correctly identified Merlin → Evil wins
- All phases tested: team_proposal, team_vote, quest, lady_of_lake, assassination, game_over
- 24 chat messages generated across the game
- Committed and pushed to main: ae76d7f

## Key Findings

### LLM output parser (bot/llm.py)
- Field extractors must separate the keyword from its value with `[^\S\n]*` (horizontal
  whitespace), NOT `\s*`. `\s` includes `\n`, so an empty `TEAM:`/`SAY:`/`TARGET:` line will
  greedily skip the newline and capture the following line as the value. Multi-field replies
  (`SAY:` then `TEAM:` on the next line) make this easy to hit.
- The free-text extractors use `([^\n]*)` (not `+`) so a present-but-empty field still matches
  and is reported with the precise "line is empty" error rather than "no line found".

### External Bot Mode Architecture
- `AVALON_BOT_MODE=external` disables internal bot loop in `manager.py`
- `GET /game/pending_bots` → lightweight polling (localhost only)
- `GET /game/bot_context/{bot_id}` → full prompt with role/knowledge/instructions (localhost + external mode only)
- Claude Code orchestration: poll → fetch context → spawn Task sub-agents → parse SAY/VOTE/TEAM/QUEST/TARGET → submit via POST /game/action
- Sonnet sub-agents work well for game decisions (fast, cheap). Opus used for assassination (needs deeper reasoning).
- Loyal players' quest votes can be submitted directly (engine enforces SUCCESS).

### Orchestration Rules
- During assassination phase, only evil players (Assassin + Minion) can chat. Good players stay silent.

### Game Loop Observations
- Sub-agents respond in correct SAY/VOTE format reliably
- Evil bots make strategic decisions (Dave chose SUCCESS on Quest 2 to maintain cover)
- Alice (Percival) correctly followed Merlin's (Claude's) rejection signals
- Assassin correctly deduced Merlin from behavioral patterns (Lady of Lake usage, team rejections)
- The prompts from `bot/prompts.py` give sub-agents enough context to play well

### Server Notes
- Server can die if backgrounded via Bash tool (use `nohup` + redirect)
- Game state persists across server restarts (SQLite)
- Token from URL: used for browser auth, player_id for localhost API calls
