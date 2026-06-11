# Claudepad - Avalon Session Memory

## Session Summaries

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
