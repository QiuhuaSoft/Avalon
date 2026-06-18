# Claudepad - Avalon Session Memory

## Session Summaries

### 2026-06-18T~UTC - Commit ballots on first cast + hammer-aware tracker + matrix tests
- Closed an engine-integrity gap in the team-proposal/voting flow. `vote_team` and
  `quest_vote` were the only actions that allowed resubmission *within* their phase (propose/
  lady_peek/assassinate already leave their phase, so they're single-shot). A re-vote
  overwrote the committed secret ballot **and emitted a duplicate event** — breaking the
  "exactly one ballot per player" invariant that `test_api.py` itself asserts
  (`team_vote count == 5`). A double-click or a mis-click on the still-live vote buttons
  (the UI leaves them clickable until the next 1.5s poll) silently flipped a committed vote.
- Fix: both handlers now ignore a resubmission (`if player.id in *_votes: return state`) —
  first cast is final, mirroring Avalon's simultaneous reveal. No legitimate flow re-votes
  (bots drop out of `pending_actions` once they vote; the UI hides the buttons after), so
  it's pure hardening. Evil players also can't "take back" a SUCCESS and FAIL later.
- Frontend: `hammerText` showed a bare "Disabled" when `hammer_auto_approve` is off — exactly
  the mode where the official five-rejection rule can instantly lose, so the tracker was least
  useful when it mattered most. Now it always shows proposal/rejection progress and flags the
  5th-proposal stakes ("reject = Evil wins" vs "(HAMMER) - auto-approve").
- Tests 116 -> 119: two engine tests (team/quest first-cast-wins, asserting the flip is
  ignored AND only one ballot event lands) + a node suite `tests/web/proposal_records.test.mjs`
  (8 cases) that was the biggest untested surface — `buildProposalRecords`/`missionSummary`/
  `hammerText`, the fold of the redacted public event stream into the proposal matrix — wired
  via `tests/test_web_logic.py` (gated on node like the XSS test). Cross-realm VM objects need
  a JSON round-trip (`plain()`) before `deepStrictEqual`.
- Verified: ruff clean, mypy --strict clean, 119 pytest + 8 node pass. Wet test on a real
  local heuristic server: re-vote guard holds at the HTTP layer (leader's APPROVE→REJECT flip
  ignored → resolves to quest, 5 ballots not 6; evil member's SUCCESS→FAIL swap ignored →
  fails=0), and a full 7p all-bot game ran to game_over (Lady fired 2x, roles revealed, no
  quest_vote leak). Noticed but left alone: `/game/start` before `/game/new` 500s on a bare
  RuntimeError instead of a clean 4xx (pre-existing, out of scope).

### 2026-06-18T~UTC - End-of-game role reveal (new user-facing feature)
- Closed a real product gap: a hidden-role game had no end reveal. `public_state` stripped
  roles unconditionally, so finishing a game just showed "Winner: evil" with no flip of who
  was Merlin/Assassin/etc. — anticlimactic and missing the genre's payoff moment.
- Engine: `public_state` now keeps roles + `lady_history` when `phase == game_over` (the only
  change to the redaction path). Individual quest ballots stay secret forever and are already
  empty by game over (cleared as each quest resolves), so nothing leaks. Safe because
  `game_over` is terminal — no decision depends on the now-public roles. Mid-game hiding is
  untouched (verified live across 6 games).
- Frontend (`game.js`): new `renderEndgameReveal` (headline + outcome sentence + per-player
  role grid) shown in the Action Menu at game over; the player table now shows true roles too.
  `describeOutcome` names how it ended (assassination hit/miss, 3 fails, or 5-rejection
  deadlock). All names rendered via `textContent` (attacker-controlled; host views with
  localhost privileges) — same XSS rule as the rest of the view. Added `.reveal-*` CSS.
- Tests 114 -> 116: engine reveal test (hidden in play / revealed at game_over / quest votes
  still secret), HTTP reveal test (drive 5-rejection game to game_over), and a node frontend
  test that `renderEndgameReveal` shows roles and renders a `<img onerror>` name as inert text.
- Verified: ruff clean, mypy --strict clean, 116 pytest pass, 3/3 node tests. Hard wet test:
  6 all-bot games — roles hidden during all active play, assassination outcomes coherent
  (hit Merlin <=> evil wins), reveal correct at game over, no quest_vote in the public log.

### 2026-06-17T~UTC - Input-hardening pass + restored the mypy gate against typed mlx_lm
- Closed three real input gaps in `game.py`, all reachable from token-authenticated
  remote clients (the engine is the enforcement boundary):
  - `create_game` accepted unsupported player counts (4, 11, ...) whenever explicit roles
    were supplied — they slipped past the role-count check and only crashed later at propose
    time ("Unsupported player count"). Now rejected up front (`MIN_PLAYERS`/`MAX_PLAYERS`).
  - `create_game` accepted duplicate and empty player IDs, which silently corrupt token maps,
    `_get_player`, and vote dicts. Now rejected.
  - Chat accepted unbounded messages (verified a 200K-char message stored + deep-copied on
    every poll). Capped at `MAX_CHAT_LENGTH` (1000); names capped at `MAX_NAME_LENGTH` (60)
    via a shared `_clean_name` used by add/rename/claim/join (also trims + rejects blank).
- Restored the "mypy --strict clean" contract: `mlx_lm` 0.30.5 ships `py.typed`, so `load()`'s
  `Union[2-tuple, 3-tuple]` return surfaced 2 latent errors in `bot/llm.py` (attributes inferred
  as `None`; union unpack). `test_typing.py` would have failed in any env with mypy + modern
  mlx_lm. Fixed with `Any` field annotations + a `cast` (runtime-identical) — 0 mypy errors.
- Tests 100 -> 111: new `tests/test_input_validation.py` (count/ID/chat/name bounds) + an
  HTTP test that an engine ValueError surfaces as 400 `{"error": ...}`. Frontend: chat input
  `maxlength` mirrors the server cap.
- Verified: ruff clean, mypy clean, 111 pass. Wet-tested a real heuristic server — all-bot game
  ran to game_over, oversized chat 400'd, bad-count/dup-id creates 400'd, no `quest_vote` leaked.

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

### mypy gate depends on the installed mlx_lm
- `mlx_lm` >= ~0.30 ships `py.typed`, so the `[[tool.mypy.overrides]] ignore_missing_imports`
  no longer turns it into `Any`. Its real `load()` type is `Union[2-tuple, 3-tuple]`. `bot/llm.py`
  pins the result with `cast(Tuple[Any, Any], ...)` and annotates `_model`/`_tokenizer` as `Any`;
  keep those if you touch the loader. `test_typing.py` only runs when `mypy` is on PATH — install
  the `dev` extra (`pip install -e '.[dev]']`) before trusting a "mypy clean" claim.

### Engine is the input-validation boundary
- `create_game` enforces 5-10 players with unique, non-empty IDs; chat/name free text is
  length-capped (`MAX_CHAT_LENGTH`/`MAX_NAME_LENGTH`). These inputs reach the engine from remote
  token-authed clients and are deep-copied into every snapshot, so bound new free-text fields too.

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
