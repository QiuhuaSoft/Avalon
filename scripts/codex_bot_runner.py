#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Tuple


def log(level: str, message: str) -> None:
    stamp = time.strftime("%H:%M:%S")
    print(f"[{stamp}] [{level}] {message}", flush=True)


def api_request(
    base_url: str,
    method: str,
    path: str,
    payload: Dict[str, Any] | None = None,
    timeout: float = 10.0,
) -> Tuple[int, Dict[str, Any]]:
    url = f"{base_url.rstrip('/')}{path}"
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Accept", "application/json")
    if payload is not None:
        req.add_header("Content-Type", "application/json")

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8")
            if not raw:
                return response.getcode(), {}
            return response.getcode(), json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"error": raw}
    except urllib.error.URLError as exc:
        return 599, {"error": str(exc)}


def ensure_codex_available(codex_cwd: str, model: str, reasoning_effort: str, timeout: int) -> None:
    if not shutil.which("codex"):
        raise RuntimeError("codex CLI not found in PATH")

    with tempfile.NamedTemporaryFile(
        prefix="avalon_codex_probe_", suffix=".txt", delete=False
    ) as fh:
        output_path = fh.name

    cmd = [
        "codex",
        "exec",
        "--ephemeral",
        "-C",
        codex_cwd,
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-o",
        output_path,
        "Reply with exactly: OK",
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = Path(output_path).read_text(encoding="utf-8").strip()
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip().splitlines()[-8:]
            raise RuntimeError(
                f"codex probe failed (exit {completed.returncode}): " + " | ".join(stderr_tail)
            )
        if output != "OK":
            raise RuntimeError(f"codex probe returned unexpected output: {output!r}")
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def ensure_external_mode(base_url: str) -> None:
    status, body = api_request(base_url, "GET", "/game/bot_context/__probe__")
    error = str(body.get("error", ""))
    if "external bot mode not enabled" in error:
        raise RuntimeError(
            "server is not running with AVALON_BOT_MODE=external; "
            "external bot controller cannot act"
        )
    if status in (200, 400, 404):
        return
    raise RuntimeError(f"unexpected bot_context probe response: HTTP {status} {body}")


def resolve_player_ref(name_to_id: Dict[str, str], value: Any) -> str | None:
    ref = str(value).strip()
    if not ref:
        return None
    if ref in name_to_id.values():
        return ref

    lowered = ref.casefold()
    for name, player_id in name_to_id.items():
        if name.casefold() == lowered:
            return player_id
    for name, player_id in name_to_id.items():
        if lowered in name.casefold() or name.casefold() in lowered:
            return player_id
    return None


def parse_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().casefold()
        if lowered in {"true", "yes", "approve", "approved", "success", "succeed", "pass"}:
            return True
        if lowered in {"false", "no", "reject", "rejected", "fail", "failed"}:
            return False
    return None


def normalize_decision(
    context: Dict[str, Any], raw: Dict[str, Any]
) -> Tuple[str, str, Dict[str, Any]]:
    phase = context.get("phase")
    name_to_id = context.get("name_to_id") or {}
    if not isinstance(name_to_id, dict):
        raise ValueError("invalid player map in context")

    say = str(raw.get("say", "")).strip()
    payload = raw.get("payload") if isinstance(raw.get("payload"), dict) else {}

    if phase == "team_proposal":
        team_raw = payload.get("team", raw.get("team", []))
        if isinstance(team_raw, str):
            team_raw = [item.strip() for item in team_raw.split(",") if item.strip()]
        if not isinstance(team_raw, list) or not team_raw:
            raise ValueError("team_proposal requires a non-empty team list")
        team: list[str] = []
        for item in team_raw:
            player_id = resolve_player_ref(name_to_id, item)
            if not player_id:
                raise ValueError(f"unknown team member reference: {item!r}")
            if player_id not in team:
                team.append(player_id)
        return say, "propose_team", {"team": team}

    if phase == "team_vote":
        approve = parse_bool(payload.get("approve", raw.get("approve")))
        if approve is None:
            raise ValueError("team_vote requires boolean approve")
        return say, "vote_team", {"approve": approve}

    if phase == "quest":
        success = parse_bool(payload.get("success", raw.get("success")))
        if success is None:
            raise ValueError("quest requires boolean success")
        return say, "quest_vote", {"success": success}

    if phase == "lady_of_lake":
        target = payload.get("target_id", raw.get("target_id", raw.get("target")))
        target_id = resolve_player_ref(name_to_id, target)
        if not target_id:
            raise ValueError("lady_of_lake requires target_id")
        return say, "lady_peek", {"target_id": target_id}

    if phase == "assassination":
        target = payload.get("target_id", raw.get("target_id", raw.get("target")))
        target_id = resolve_player_ref(name_to_id, target)
        if not target_id:
            raise ValueError("assassination requires target_id")
        return say, "assassinate", {"target_id": target_id}

    raise ValueError(f"unsupported phase for external action: {phase!r}")


def extract_json(text: str) -> Dict[str, Any]:
    text = text.strip()
    if not text:
        raise ValueError("empty model output")
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < 0 or end <= start:
        raise ValueError("no JSON object found in model output")
    snippet = text[start : end + 1]
    return json.loads(snippet)


def codex_exec(
    prompt: str,
    codex_cwd: str,
    model: str,
    reasoning_effort: str,
    timeout: int,
) -> str:
    with tempfile.NamedTemporaryFile(prefix="avalon_codex_out_", suffix=".txt", delete=False) as fh:
        output_path = fh.name

    cmd = [
        "codex",
        "exec",
        "--ephemeral",
        "-C",
        codex_cwd,
        "-s",
        "read-only",
        "--skip-git-repo-check",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "-o",
        output_path,
        prompt,
    ]
    try:
        completed = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        output = Path(output_path).read_text(encoding="utf-8")
        if completed.returncode != 0:
            stderr_tail = (completed.stderr or "").strip().splitlines()[-8:]
            raise RuntimeError(
                f"codex call failed (exit {completed.returncode}): " + " | ".join(stderr_tail)
            )
        if not output.strip():
            raise RuntimeError("codex call produced empty output")
        return output
    finally:
        try:
            os.remove(output_path)
        except OSError:
            pass


def build_decision_prompt(context: Dict[str, Any]) -> str:
    phase = context.get("phase")
    bot_name = context.get("bot_name")
    full_prompt = context.get("full_prompt", "")
    name_to_id = context.get("name_to_id", {})

    return (
        "You are controlling one Avalon bot action.\n"
        "Use the game prompt below as the canonical game context.\n\n"
        "--- BEGIN GAME PROMPT ---\n"
        f"{full_prompt}\n"
        "--- END GAME PROMPT ---\n\n"
        f"Bot: {bot_name}\n"
        f"Phase: {phase}\n"
        f"Player name-to-id map: {json.dumps(name_to_id, ensure_ascii=True)}\n\n"
        "Return ONLY one JSON object with this shape:\n"
        '{"say":"optional short chat line, may be empty","action_type":"...","payload":{...}}\n\n'
        "Rules:\n"
        '- For "team_proposal": action_type="propose_team", payload={"team":["player_id", "..."]}\n'
        '- For "team_vote": action_type="vote_team", payload={"approve":true|false}\n'
        '- For "quest": action_type="quest_vote", payload={"success":true|false}\n'
        '- For "lady_of_lake": action_type="lady_peek", payload={"target_id":"player_id"}\n'
        '- For "assassination": action_type="assassinate", payload={"target_id":"player_id"}\n'
        "Use player IDs in payload, not names.\n"
        "No markdown. No extra keys. JSON only."
    )


def decide_with_codex(
    context: Dict[str, Any],
    codex_cwd: str,
    model: str,
    reasoning_effort: str,
    timeout: int,
    retries: int,
) -> Tuple[str, str, Dict[str, Any]]:
    base_prompt = build_decision_prompt(context)
    prompt = base_prompt
    last_error = "unknown"

    for attempt in range(1, retries + 1):
        output = codex_exec(
            prompt,
            codex_cwd=codex_cwd,
            model=model,
            reasoning_effort=reasoning_effort,
            timeout=timeout,
        )
        try:
            raw = extract_json(output)
            return normalize_decision(context, raw)
        except Exception as exc:
            last_error = str(exc)
            prompt = (
                f"{base_prompt}\n\n"
                f"Your previous output was invalid: {last_error}\n"
                "Retry now with valid JSON only."
            )
            log(
                "WARN",
                f"invalid model output for {context.get('bot_id')} "
                f"(attempt {attempt}/{retries})",
            )

    raise RuntimeError(f"could not parse valid decision after {retries} attempts: {last_error}")


def post_action(base_url: str, bot_id: str, action_type: str, payload: Dict[str, Any]) -> None:
    status, body = api_request(
        base_url,
        "POST",
        "/game/action",
        {"player_id": bot_id, "action_type": action_type, "payload": payload},
    )
    if status != 200:
        raise RuntimeError(f"action failed: HTTP {status} {body}")


def run_loop(args: argparse.Namespace) -> int:
    log("INFO", "checking codex connectivity")
    ensure_codex_available(args.codex_cwd, args.model, args.reasoning_effort, args.codex_timeout)
    log("INFO", "codex probe passed")

    log("INFO", "checking avalon external bot mode")
    ensure_external_mode(args.base_url)
    log("INFO", "external bot mode probe passed")

    log("INFO", "bot runner started")
    while True:
        status, pending = api_request(args.base_url, "GET", "/game/pending_bots")
        if status != 200:
            log("ERROR", f"pending bot poll failed: HTTP {status} {pending}")
            if args.strict_fail:
                return 1
            time.sleep(args.poll_interval)
            continue

        bot_ids = pending.get("pending_bots", [])
        if not bot_ids:
            time.sleep(args.poll_interval)
            continue

        for bot_id in bot_ids:
            encoded_id = urllib.parse.quote(str(bot_id), safe="")
            status, context = api_request(args.base_url, "GET", f"/game/bot_context/{encoded_id}")
            if status != 200:
                log("WARN", f"skipping bot {bot_id}: HTTP {status} {context}")
                error_text = str(context.get("error", ""))
                if args.strict_fail and "external bot mode not enabled" in error_text:
                    return 1
                continue

            try:
                say, action_type, payload = decide_with_codex(
                    context=context,
                    codex_cwd=args.codex_cwd,
                    model=args.model,
                    reasoning_effort=args.reasoning_effort,
                    timeout=args.codex_timeout,
                    retries=args.retries,
                )
            except Exception as exc:
                log("ERROR", f"decision failed for bot {bot_id}: {exc}")
                if args.strict_fail:
                    return 1
                continue

            if say:
                try:
                    post_action(args.base_url, bot_id, "chat", {"message": say[:300]})
                except Exception as exc:
                    log("WARN", f"chat submit failed for {bot_id}: {exc}")

            try:
                post_action(args.base_url, bot_id, action_type, payload)
                log("INFO", f"{bot_id} -> {action_type} {json.dumps(payload, ensure_ascii=True)}")
            except Exception as exc:
                log("ERROR", f"action submit failed for bot {bot_id}: {exc}")
                if args.strict_fail:
                    return 1


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description="Drive Avalon external bots via Codex CLI.")
    parser.add_argument("--base-url", default=os.getenv("AVALON_BASE_URL", "http://localhost:8010"))
    parser.add_argument("--model", default=os.getenv("AVALON_CODEX_MODEL", "gpt-5.3-codex"))
    parser.add_argument(
        "--reasoning-effort",
        default=os.getenv("AVALON_CODEX_REASONING", "low"),
        help="Codex model_reasoning_effort value (low, medium, high).",
    )
    parser.add_argument("--codex-cwd", default=str(root))
    parser.add_argument(
        "--poll-interval", type=float, default=float(os.getenv("AVALON_BOT_POLL", "0.5"))
    )
    parser.add_argument(
        "--codex-timeout",
        type=int,
        default=int(os.getenv("AVALON_CODEX_TIMEOUT", "120")),
        help="Timeout per codex decision call (seconds).",
    )
    parser.add_argument(
        "--retries",
        type=int,
        default=int(os.getenv("AVALON_CODEX_RETRIES", "2")),
        help="Decision retries when model output is invalid.",
    )
    parser.add_argument(
        "--strict-fail",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Exit immediately on control-plane errors instead of silently idling.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return run_loop(args)
    except KeyboardInterrupt:
        log("INFO", "stopped by user")
        return 0
    except Exception as exc:
        log("ERROR", str(exc))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
