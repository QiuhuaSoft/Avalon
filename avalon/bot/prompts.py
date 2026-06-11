from __future__ import annotations

import random
from typing import List, Optional

from ..game import alignment_for, team_size
from ..models import Alignment, GameState, Phase, Player, Role

# Example dialogue patterns extracted from Avalon-NLU dataset
EVIL_DIALOGUE_EXAMPLES = [
    "i'll just go ahead and approve it. its just the first round.",
    "i want to note that it's a bit weird that they did not put themselves on the party.",
    "nothing certain, but it is a little suspicious, that's all.",
    "i think they're suspicious since they voted no in last round.",
    "typically if you are good, you would want to put yourself on the party.",
    "it would be weird for them to be bad, but they did also vote no which is a bit suspicious.",
    "this looks good to me. however as a good person, "
    "i would like to suggest myself to be on the quest.",
    "i agree with this party, no objections from me.",
    "why not put yourself on the party? that's a bit odd.",
    "i'm not totally convinced but i'll go along with it for now.",
]

GOOD_DIALOGUE_EXAMPLES = [
    "this seems reasonable to me. let's see how the vote goes.",
    "yeah, nothing to go off on right now, so i am fine with this.",
    "we have nothing else to go off of so i am fine with this party.",
    "i'd rather keep sticking with the first party and adding to it.",
    "let's just stick with this and gain some information.",
    "i guess they're a little suspicious for not including themselves in the first quest.",
    "people who are eager to make extreme allegations are also suspicious.",
    "i am good, so it won't fail because of me.",
    "this strategy sounds right to me. i would approve it.",
    "let's see what happens and go from there.",
]

MERLIN_DIALOGUE_EXAMPLES = [
    "hmm so this is what i would suggest, we had a party succeed last time.",
    "i would like to quickly narrow down this scope and test them.",
    "if the quest succeeds, we gain a success. if it fails we have something to focus on.",
    "given the first round, we have pretty strong evidence about what happened.",
    "a normal percival should not easily reveal themselves.",
    "i have a hunch about this but let's see how it plays out.",
    "based on the voting patterns, i think we should try this combination.",
]


def _sample_dialogue_examples(player: Player) -> str:
    """Sample a mix of dialogue examples based on player role."""
    alignment = alignment_for(player.role)

    if player.role == Role.merlin:
        # Merlin: 2 merlin + 1 good + 1 evil
        samples = (
            random.sample(MERLIN_DIALOGUE_EXAMPLES, min(2, len(MERLIN_DIALOGUE_EXAMPLES)))
            + random.sample(GOOD_DIALOGUE_EXAMPLES, 1)
            + random.sample(EVIL_DIALOGUE_EXAMPLES, 1)
        )
    elif alignment == Alignment.evil:
        # Evil: 3 evil + 1 good
        samples = (
            random.sample(EVIL_DIALOGUE_EXAMPLES, min(3, len(EVIL_DIALOGUE_EXAMPLES)))
            + random.sample(GOOD_DIALOGUE_EXAMPLES, 1)
        )
    else:
        # Good: 3 good + 1 evil
        samples = (
            random.sample(GOOD_DIALOGUE_EXAMPLES, min(3, len(GOOD_DIALOGUE_EXAMPLES)))
            + random.sample(EVIL_DIALOGUE_EXAMPLES, 1)
        )

    random.shuffle(samples)
    return "\n".join(f'- "{s}"' for s in samples)


def build_system_prompt(player: Player, knowledge: List[str]) -> str:
    role = player.role.value if player.role else "Unknown"
    alignment = alignment_for(player.role)
    alignment_str = alignment.value if alignment else "Unknown"
    facts = "\n".join(f"- {item}" for item in knowledge) or "- None"

    # Role-specific personality guidance
    if alignment == Alignment.evil:
        personality = (
            "You are EVIL. Your goal is to sabotage quests and avoid detection.\n"
            "DECEPTION IS KEY: Never reveal your true alignment or reasoning!\n"
            "- Pretend to be good and helpful\n"
            "- Cast SUBTLE suspicion on good players (not too aggressive)\n"
            "- Defend your evil teammates indirectly\n"
            "- Act confused or concerned, not aggressive"
        )
    else:
        personality = (
            "You are GOOD. Your goal is to find evil players and succeed on quests.\n"
            "- Share your genuine suspicions and observations\n"
            "- Pay attention to voting patterns and behavior\n"
            "- Be willing to take risks to find information"
        )

    # Add sampled dialogue examples
    examples = _sample_dialogue_examples(player)
    personality += f"\n\nExample things players say:\n{examples}"

    # Special role guidance
    role_tips = ""
    if player.role == Role.merlin:
        role_tips = (
            "\nYou are MERLIN - you know who is evil! But be careful:\n"
            "- Don't be too obvious or the Assassin will target you\n"
            "- Guide good players subtly by framing insights as logical deductions\n"
            "- Say things like 'given the voting pattern...' rather than stating facts directly"
        )
    elif player.role == Role.assassin:
        role_tips = (
            "\nYou are the ASSASSIN - if good wins 3 quests, you can still win by killing Merlin.\n"
            "- Watch for players who seem to 'know too much'\n"
            "- Note who consistently identifies evil players\n"
            "- Players who guide the team subtly without revealing info might be Merlin"
        )
    elif player.role == Role.morgana:
        role_tips = (
            "\nYou are MORGANA - you appear as Merlin to Percival.\n"
            "- Try to act like Merlin by giving 'subtle guidance'\n"
            "- Frame suspicions as logical deductions to seem like Merlin\n"
            "- Claim to be Merlin if it helps confuse Percival"
        )
    elif player.role == Role.percival:
        role_tips = (
            "\nYou are PERCIVAL - you see Merlin and Morgana but don't know which is which.\n"
            "- Try to figure out who the real Merlin is by their behavior\n"
            "- Protect whoever you think is Merlin\n"
            "- Be careful not to reveal who you think Merlin is"
        )

    return (
        f"You are playing Avalon as {player.name}.\n"
        f"Your role: {role}\n"
        f"Your alignment: {alignment_str}\n\n"
        f"{personality}{role_tips}\n\n"
        "What you know:\n"
        f"{facts}\n\n"
        "IMPORTANT: Speak naturally! Keep messages short (1-2 sentences). "
        "Sound like a real player, not an AI."
    )


def build_context(state: GameState, player_id: str, recent_chat: List[str]) -> str:
    leader = state.players[state.leader_index]
    team_needed = team_size(state.config.player_count, state.quest_number)
    id_to_name = {p.id: p.name for p in state.players}
    proposed_names = [id_to_name.get(pid, pid) for pid in state.proposed_team]

    # Build player roster
    player_roster = ", ".join(p.name for p in state.players)

    # Quest history summary
    quest_history_str = ""
    if state.quest_history:
        results = ["✓" if r.succeeded else "✗" for r in state.quest_history]
        quest_history_str = f"Quest history: {' '.join(results)}\n"

    return (
        "=== GAME STATE ===\n"
        f"Players: {player_roster}\n"
        f"Quest {state.quest_number} | Successes: {state.success_count}"
        f" | Fails: {state.fail_count}\n"
        f"{quest_history_str}"
        f"Leader: {leader.name}\n"
        f"Team size needed: {team_needed}\n"
        f"Rejected proposals this round: {state.proposal_attempts}\n"
        f"Proposed team: {', '.join(proposed_names) or 'None yet'}\n\n"
        "=== RECENT DISCUSSION ===\n"
        + "\n".join(recent_chat or ["(no chat yet)"])
    )


def build_action_instructions(state: GameState, player: Player) -> str:
    """Build phase-specific instructions with chat + action format."""
    player_names = [p.name for p in state.players]
    team_needed = team_size(state.config.player_count, state.quest_number)

    if state.phase == Phase.team_proposal:
        return _team_proposal_instructions(player, player_names, team_needed)

    if state.phase == Phase.team_vote:
        return _team_vote_instructions(state, player)

    if state.phase == Phase.quest:
        return _quest_instructions(player)

    if state.phase == Phase.assassination and player.role == Role.assassin:
        # Get evil teammate names so assassin doesn't target them
        evil_names = [
            p.name for p in state.players
            if p.role and alignment_for(p.role) == Alignment.evil and p.id != player.id
        ]
        return _assassination_instructions(player, player_names, evil_names)

    if state.phase == Phase.lady_of_lake and state.lady_holder_id == player.id:
        return _lady_of_lake_instructions(player, player_names)

    return "No action needed. You may chat or wait."


def _team_proposal_instructions(player: Player, player_names: List[str], required_size: int) -> str:
    names_list = ", ".join(player_names)
    example_names = player_names[:required_size]
    other_player = player_names[1] if len(player_names) > 1 else "someone"

    return f"""=== YOUR TASK ===
You are the LEADER. Propose a team of exactly {required_size} players.

First, say something brief to the group (1-2 sentences max).
Then, output your team selection.

FORMAT:
SAY: [Brief explanation - sound natural, not robotic]
TEAM: Name1, Name2{", Name3" if required_size > 2 else ""}

EXAMPLE 1 (early game):
SAY: random given no information. included myself as i am good of course.
TEAM: {player.name}, {other_player}

EXAMPLE 2 (with info):
SAY: i'd rather keep sticking with the last successful party and add one more.
TEAM: {", ".join(example_names)}

Available players: {names_list}
Your response:"""


def _team_vote_instructions(state: GameState, player: Player) -> str:
    id_to_name = {p.id: p.name for p in state.players}
    proposed_names = [id_to_name.get(pid, pid) for pid in state.proposed_team]
    team_str = ", ".join(proposed_names)
    leader = state.players[state.leader_index]

    return f"""=== YOUR TASK ===
Vote on the proposed team: {team_str} (proposed by {leader.name})

First, say something brief (1-2 sentences max).
Then, cast your vote.

FORMAT:
SAY: [Brief comment - sound natural]
VOTE: APPROVE or REJECT

EXAMPLE (approving):
SAY: this seems reasonable to me. let's see how it goes.
VOTE: APPROVE

EXAMPLE (approving early game):
SAY: not enough info for now, good on party.
VOTE: APPROVE

EXAMPLE (rejecting):
SAY: i'm not totally sure who to trust, but i disagree with this party.
VOTE: REJECT

Your response:"""


def _quest_instructions(player: Player) -> str:
    alignment = alignment_for(player.role)
    if alignment == Alignment.loyal:
        alignment_note = "As a LOYAL servant, you MUST vote SUCCESS. You cannot fail quests."
        example_say = "let's do this! hoping for a success."
        example_vote = "SUCCESS"
    else:
        alignment_note = (
            "As EVIL, you may vote FAIL to sabotage the quest.\n"
            "Consider: Is this a good time to fail? Will you be suspected?\n"
            "If multiple evil on quest, coordinate - don't both fail!"
        )
        example_say = "i hope this quest goes well for our team."
        example_vote = "SUCCESS"

    return f"""=== YOUR TASK ===
You are on the quest! Submit your secret vote.
{alignment_note}

Say something brief (your VOTE is secret - don't reveal it!).

FORMAT:
SAY: [Brief encouraging comment - never hint at your vote!]
QUEST: SUCCESS or FAIL

EXAMPLE:
SAY: {example_say}
QUEST: {example_vote}

Your response:"""


def _assassination_instructions(
    player: Player, player_names: List[str], evil_names: Optional[List[str]] = None
) -> str:
    # Exclude self and known evil teammates - they can't be Merlin
    evil_names = evil_names or []
    targets = [name for name in player_names if name != player.name and name not in evil_names]
    targets_list = ", ".join(targets)
    suspect = targets[0] if targets else "someone"
    example_target = targets[0] if targets else "Unknown"

    return f"""=== YOUR TASK ===
Good has won 3 quests, but you can still win!
As the ASSASSIN, identify and kill Merlin to steal victory.

Think about:
- Who seemed to "know too much" about evil players?
- Who guided the team with subtle suggestions?
- Who avoided being on failed quests suspiciously well?

FORMAT:
SAY: [Your reasoning - who do you suspect is Merlin?]
TARGET: PlayerName

EXAMPLE:
SAY: i noticed {suspect} always seemed to guide us away from bad parties. they might be merlin.
TARGET: {example_target}

Possible targets: {targets_list}
Your response:"""


def _lady_of_lake_instructions(player: Player, player_names: List[str]) -> str:
    targets = [name for name in player_names if name != player.name]
    targets_list = ", ".join(targets)

    return f"""=== YOUR TASK ===
You hold the Lady of the Lake! Choose someone to investigate.
You will secretly learn if they are Good or Evil.

FORMAT:
SAY: [Brief reason for your choice]
INSPECT: PlayerName

EXAMPLE:
SAY: i want to check {targets[0] if targets else "someone"} - their voting has been inconsistent.
INSPECT: {targets[0] if targets else "Unknown"}

Possible targets: {targets_list}
Your response:"""
