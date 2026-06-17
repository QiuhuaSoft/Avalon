#!/usr/bin/env python3
"""Analyze the Avalon-NLU dataset to extract dialogue patterns for bot training."""

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

DATASET_PATH = Path("/Users/discordwell/Projects/Avalon-NLU/dataset")

EVIL_ROLES = {"morgana", "assassin"}
GOOD_ROLES = {"merlin", "percival", "servant-1", "servant-2"}


def load_all_games() -> List[Dict[str, Any]]:
    """Load all game JSON files."""
    games = []
    for json_file in DATASET_PATH.glob("*.json"):
        with open(json_file) as f:
            game = json.load(f)
            game["_filename"] = json_file.name
            games.append(game)
    return games


def analyze_games(games: List[Dict]) -> Dict:
    """Analyze games to extract patterns."""
    stats = {
        "total_games": len(games),
        "total_messages": 0,
        "messages_by_role": defaultdict(list),
        "messages_by_alignment": {"good": [], "evil": []},
        "persuasion_strategies": defaultdict(list),
        "deception_strategies": defaultdict(list),
        "messages_by_quest": defaultdict(list),
    }

    for game in games:
        users = game["users"]
        messages = game["messages"]
        persuasion = game.get("persuasion", {})

        # Build lookup from message ID to persuasion info
        mid_to_persuasion = {}
        for p in persuasion.values():
            mid_to_persuasion[p["mid"]] = p

        # Build lookup from player name to role
        name_to_role = {u["name"]: u["role"] for u in users.values()}

        for msg_data in messages.values():
            player = msg_data["player"]
            if player == "system":
                continue

            stats["total_messages"] += 1
            msg_text = msg_data["msg"]
            quest = msg_data.get("quest", 0)
            mid = msg_data.get("mid", "")

            role = name_to_role.get(player, "unknown")
            alignment = "evil" if role in EVIL_ROLES else "good"

            # Get persuasion/deception labels
            persuasion_info = mid_to_persuasion.get(mid, {})
            persuasion_type = persuasion_info.get("persuasion", "unknown")
            deception_type = persuasion_info.get("deception")

            entry = {
                "text": msg_text,
                "role": role,
                "alignment": alignment,
                "quest": quest,
                "persuasion": persuasion_type,
                "deception": deception_type,
                "game": game["_filename"],
            }

            stats["messages_by_role"][role].append(entry)
            stats["messages_by_alignment"][alignment].append(entry)
            stats["persuasion_strategies"][persuasion_type].append(entry)
            if deception_type:
                stats["deception_strategies"][deception_type].append(entry)
            stats["messages_by_quest"][quest].append(entry)

    return stats


def print_examples(stats: Dict, category: str, items: List[Dict], n: int = 5):
    """Print example messages from a category."""
    print(f"\n{'='*60}")
    print(f"{category} ({len(items)} total)")
    print("=" * 60)
    for item in items[:n]:
        role_tag = f"[{item['role'].upper()}]"
        deception_tag = f" (deception: {item['deception']})" if item["deception"] else ""
        print(f"  {role_tag} {item['text']}")
        print(f"    → persuasion: {item['persuasion']}{deception_tag}")
        print()


def main():
    print("Loading Avalon-NLU dataset...")
    games = load_all_games()
    print(f"Loaded {len(games)} games")

    stats = analyze_games(games)
    print(f"\nTotal messages: {stats['total_messages']}")

    # Print stats
    print("\n" + "=" * 60)
    print("MESSAGES BY ALIGNMENT")
    print("=" * 60)
    print(f"  Good players: {len(stats['messages_by_alignment']['good'])} messages")
    print(f"  Evil players: {len(stats['messages_by_alignment']['evil'])} messages")

    print("\n" + "=" * 60)
    print("MESSAGES BY ROLE")
    print("=" * 60)
    for role, msgs in sorted(stats["messages_by_role"].items()):
        print(f"  {role}: {len(msgs)} messages")

    print("\n" + "=" * 60)
    print("PERSUASION STRATEGIES")
    print("=" * 60)
    for strategy, msgs in sorted(stats["persuasion_strategies"].items(), key=lambda x: -len(x[1])):
        print(f"  {strategy}: {len(msgs)} messages")

    print("\n" + "=" * 60)
    print("DECEPTION STRATEGIES (Evil players only)")
    print("=" * 60)
    for strategy, msgs in sorted(stats["deception_strategies"].items(), key=lambda x: -len(x[1])):
        print(f"  {strategy}: {len(msgs)} messages")

    # Print example messages
    by_role = stats["messages_by_role"]
    print_examples(stats, "MERLIN EXAMPLES", by_role.get("merlin", []), 8)
    print_examples(stats, "EVIL (MORGANA) EXAMPLES", by_role.get("morgana", []), 8)
    print_examples(stats, "EVIL (ASSASSIN) EXAMPLES", by_role.get("assassin", []), 8)
    print_examples(stats, "PERCIVAL EXAMPLES", by_role.get("percival", []), 5)

    # Print deception examples
    deception = stats["deception_strategies"]
    print_examples(stats, "DECEPTION: OMISSION", deception.get("omission", []), 8)
    print_examples(stats, "DECEPTION: INFLUENCE", deception.get("influence", []), 8)

    # Print logical deduction examples (most strategic)
    deduction = stats["persuasion_strategies"].get("logical deduction", [])
    print_examples(stats, "LOGICAL DEDUCTION (Most Strategic)", deduction, 10)


if __name__ == "__main__":
    main()
