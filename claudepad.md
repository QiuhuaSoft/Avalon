# Claudepad - Avalon Session Memory

## Session Summaries

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
