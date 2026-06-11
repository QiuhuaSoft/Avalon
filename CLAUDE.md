# Avalon Project

## Development
- Server: `python -m avalon.main` (runs on port 8010)
- Tests: `python -m pytest` (heuristic bots, temp DB — no LLM needed)
- Smoke test: `scripts/smoke_game.sh` (boots a real server, opens the game page)
- Debug logging: `AVALON_DEBUG=1`

## Bot Modes
- Heuristic (fast, no LLM): `AVALON_BOT_MODE=heuristic`
- LLM (chatty bots): `AVALON_BOT_MODE=llm`
- Recommended LLM model: `QWEN_MODEL="mlx-community/Qwen2.5-7B-Instruct-4bit"` (7B is fast enough, 72B times out)

## Key Files
- API routes: `avalon/api.py`
- Bot logic: `avalon/bot/policy.py`, `avalon/bot/prompts.py`
- Frontend: `avalon/web/` (lobby.js, game.html, etc.)
- Game engine: `avalon/game.py`
