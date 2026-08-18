from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str = os.getenv("AVALON_HOST", "0.0.0.0")
    port: int = int(os.getenv("AVALON_PORT", "8010"))
    database_path: str = os.getenv("AVALON_DB", "/tmp/avalon/game.sqlite")
    bot_mode: str = os.getenv("AVALON_BOT_MODE", "llm")
    qwen_model: str = os.getenv(
        "QWEN_MODEL",
        "mlx-community/Qwen2.5-72B-Instruct-4bit",
    )
    max_recent_chat: int = int(os.getenv("AVALON_CHAT_RECENT", "30"))
    action_timeout_seconds: int = int(os.getenv("AVALON_ACTION_TIMEOUT", "120"))
    admin_password: str = os.getenv("AVALON_ADMIN_PASSWORD", "admin")


SETTINGS = Settings()
