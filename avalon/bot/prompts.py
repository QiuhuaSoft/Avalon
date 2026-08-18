from __future__ import annotations

import random
from typing import List, Optional

from ..game import alignment_for, team_size
from ..models import Alignment, GameState, Phase, Player, Role

# Example dialogue patterns extracted from Avalon-NLU dataset
EVIL_DIALOGUE_EXAMPLES = [
    "我就先同意了吧，反正只是第一轮。",
    "我想指出，他们没有把自己放进队伍里，这有点奇怪。",
    "不确定，但确实有点可疑。",
    "我觉得他们很可疑，因为上一轮投了反对票。",
    "一般来说，如果你是好人，你会想把自己放进队伍里。",
    "他们不太像是坏人，但他们确实投了反对票，这有点可疑。",
    "这个队伍看起来不错。不过作为好人，我想建议自己加入任务。",
    "我同意这个队伍，没有异议。",
    "为什么不把自己放进队伍里？这有点奇怪。",
    "我不是完全信服，但暂时先同意吧。",
]

GOOD_DIALOGUE_EXAMPLES = [
    "这对我来说看起来合理。看看投票结果吧。",
    "是啊，目前没什么线索，所以我同意这个队伍。",
    "我们没有其他线索，所以我同意这个队伍。",
    "我更倾向于保持第一个队伍，再加一个人。",
    "我们就先这样吧，收集一些信息。",
    "我觉得他们没把自己放进第一个任务队伍里，有点可疑。",
    "急于做出极端指控的人也很可疑。",
    "我是好人，所以任务不会因为我而失败。",
    "这个策略听起来对我有利。我会同意的。",
    "看看会发生什么，然后再做决定。",
]

MERLIN_DIALOGUE_EXAMPLES = [
    "嗯，这是我的建议，上次的队伍成功了。",
    "我想快速缩小范围来测试他们。",
    "如果任务成功，我们获得一次成功。如果失败，我们有了重点关注对象。",
    "根据第一轮的情况，我们有了相当有力的证据。",
    "一个正常的派西维尔不应该轻易暴露自己。",
    "我对此有预感，但让我们看看结果如何。",
    "根据投票模式，我认为我们应该尝试这个组合。",
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
    role = player.role.value if player.role else "未知"
    alignment = alignment_for(player.role)
    alignment_str = "正义方" if alignment == Alignment.loyal else "邪恶方" if alignment == Alignment.evil else "未知"
    facts = "\n".join(f"- {item}" for item in knowledge) or "- 无"

    # Role-specific personality guidance
    if alignment == Alignment.evil:
        personality = (
            "你是邪恶方。你的目标是破坏任务并避免被发现。\n"
            "欺骗是关键：绝不要暴露你的真实阵营或推理！\n"
            "- 假装是好人并表现得有帮助\n"
            "- 对好人施加微妙的怀疑（不要太激进）\n"
            "- 间接保护你的邪恶方队友\n"
            "- 表现得困惑或担忧，而不是有攻击性"
        )
    else:
        personality = (
            "你是正义方。你的目标是找出邪恶方玩家并完成任务。\n"
            "- 分享你真实的怀疑和观察\n"
            "- 注意投票模式和行为\n"
            "- 愿意冒险获取信息"
        )

    # Add sampled dialogue examples
    examples = _sample_dialogue_examples(player)
    personality += f"\n\n玩家常说的话：\n{examples}"

    # Special role guidance
    role_tips = ""
    if player.role == Role.merlin:
        role_tips = (
            "\n你是梅林——你知道谁是邪恶方！但要小心：\n"
            "- 不要太明显，否则刺客会刺杀你\n"
            "- 通过将洞察包装为逻辑推理来微妙地引导好人\n"
            "- 说'根据投票模式...'而不是直接陈述事实"
        )
    elif player.role == Role.assassin:
        role_tips = (
            "\n你是刺客——如果正义方完成3个任务，你仍然可以通过杀死梅林来获胜。\n"
            "- 注意那些似乎'知道太多'的玩家\n"
            "- 记住谁一直在指认邪恶方玩家\n"
            "- 那些微妙引导队伍但不暴露信息的玩家可能是梅林"
        )
    elif player.role == Role.morgana:
        role_tips = (
            "\n你是莫甘娜——你在派西维尔眼中看起来像梅林。\n"
            "- 试着通过给出'微妙引导'来表现得像梅林\n"
            "- 将怀疑包装为逻辑推理以显得像梅林\n"
            "- 如果有助于迷惑派西维尔，可以声称自己是梅林"
        )
    elif player.role == Role.percival:
        role_tips = (
            "\n你是派西维尔——你能看到梅林和莫甘娜，但不知道谁是谁。\n"
            "- 试着通过行为来判断谁是真正的梅林\n"
            "- 保护你认为是梅林的人\n"
            "- 小心不要暴露你认为谁是梅林"
        )

    return (
        f"你正在玩阿瓦隆，你是 {player.name}。\n"
        f"你的身份：{role}\n"
        f"你的阵营：{alignment_str}\n\n"
        f"{personality}{role_tips}\n\n"
        "你已知的信息：\n"
        f"{facts}\n\n"
        "重要：自然地说话！保持消息简短（1-2句话）。"
        "听起来像一个真正的玩家，而不是AI。"
    )


def build_context(state: GameState, player_id: str, recent_chat: List[str]) -> str:
    leader = state.players[state.leader_index]
    team_needed = team_size(state.config.player_count, state.quest_number)
    id_to_name = {p.id: p.name for p in state.players}
    proposed_names = [id_to_name.get(pid, pid) for pid in state.proposed_team]

    # Build player roster
    player_roster = "、".join(p.name for p in state.players)

    # Quest history summary
    quest_history_str = ""
    if state.quest_history:
        results = ["✓" if r.succeeded else "✗" for r in state.quest_history]
        quest_history_str = f"任务历史：{' '.join(results)}\n"

    return (
        "=== 游戏状态 ===\n"
        f"玩家：{player_roster}\n"
        f"任务 {state.quest_number} | 成功：{state.success_count}"
        f" | 失败：{state.fail_count}\n"
        f"{quest_history_str}"
        f"队长：{leader.name}\n"
        f"需要队伍人数：{team_needed}\n"
        f"本轮被拒绝的提议：{state.proposal_attempts}\n"
        f"提议的队伍：{', '.join(proposed_names) or '暂无'}\n\n"
        "=== 最近讨论 ===\n"
        + "\n".join(recent_chat or ["（暂无聊天）"])
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
        # The Lady may not be re-used on anyone who has already held it, so keep
        # past holders out of the suggested targets the bot is shown.
        prior_holder_ids = {entry["holder_id"] for entry in state.lady_history}
        prior_holder_names = [p.name for p in state.players if p.id in prior_holder_ids]
        return _lady_of_lake_instructions(player, player_names, prior_holder_names)

    return "无需操作。你可以聊天或等待。"


def _team_proposal_instructions(player: Player, player_names: List[str], required_size: int) -> str:
    names_list = "、".join(player_names)
    example_names = player_names[:required_size]
    other_player = player_names[1] if len(player_names) > 1 else "某人"

    return f"""=== 你的任务 ===
你是队长。提议一个恰好 {required_size} 名玩家的队伍。

首先，对大家说点什么（最多1-2句话）。
然后，输出你的队伍选择。

格式：
SAY: [简短解释 - 听起来自然，不要像机器人]
TEAM: 名字1, 名字2{", 名字3" if required_size > 2 else ""}

示例1（游戏早期）：
SAY: 没有信息就随机选了。当然把我自己也放进去了，因为我是好人。
TEAM: {player.name}, {other_player}

示例2（有信息时）：
SAY: 我更倾向于保持上次成功的队伍，再加一个人。
TEAM: {", ".join(example_names)}

可选玩家：{names_list}
你的回答："""


def _team_vote_instructions(state: GameState, player: Player) -> str:
    id_to_name = {p.id: p.name for p in state.players}
    proposed_names = [id_to_name.get(pid, pid) for pid in state.proposed_team]
    team_str = "、".join(proposed_names)
    leader = state.players[state.leader_index]

    return f"""=== 你的任务 ===
对提议的队伍投票：{team_str}（由 {leader.name} 提议）

首先，说点什么（最多1-2句话）。
然后，投出你的票。

格式：
SAY: [简短评论 - 听起来自然]
VOTE: APPROVE 或 REJECT

示例（同意）：
SAY: 这对我来说看起来合理。看看结果如何。
VOTE: APPROVE

示例（游戏早期同意）：
SAY: 目前信息不够，队伍还行。
VOTE: APPROVE

示例（拒绝）：
SAY: 我不确定该信任谁，但我不同意这个队伍。
VOTE: REJECT

你的回答："""


def _quest_instructions(player: Player) -> str:
    alignment = alignment_for(player.role)
    if alignment == Alignment.loyal:
        alignment_note = '作为忠臣，你必须投"成功"。你不能让任务失败。'
        example_say = "加油！希望任务成功。"
        example_vote = "SUCCESS"
    else:
        alignment_note = (
            '作为邪恶方，你可以投"失败"来破坏任务。\n'
            "考虑一下：现在是破坏的好时机吗？你会被怀疑吗？\n"
            "如果队伍中有多个邪恶方，要协调——不要都投失败！"
        )
        example_say = "我希望这次任务对我们的队伍顺利。"
        example_vote = "SUCCESS"

    return f"""=== 你的任务 ===
你正在执行任务！提交你的秘密投票。
{alignment_note}

说点什么（你的投票是秘密的——不要暴露！）。

格式：
SAY: [简短的鼓励性评论——绝不要暗示你的投票！]
QUEST: SUCCESS 或 FAIL

示例：
SAY: {example_say}
QUEST: {example_vote}

你的回答："""


def _assassination_instructions(
    player: Player, player_names: List[str], evil_names: Optional[List[str]] = None
) -> str:
    # Exclude self and known evil teammates - they can't be Merlin
    evil_names = evil_names or []
    targets = [name for name in player_names if name != player.name and name not in evil_names]
    targets_list = "、".join(targets)
    suspect = targets[0] if targets else "某人"
    example_target = targets[0] if targets else "未知"

    return f"""=== 你的任务 ===
正义方已经完成了3个任务，但你仍然可以获胜！
作为刺客，找出并杀死梅林来夺取胜利。

想一想：
- 谁似乎对邪恶方玩家'知道太多'？
- 谁通过微妙的建议引导队伍？
- 谁可疑地避开了失败的任务？

格式：
SAY: [你的推理——你怀疑谁是梅林？]
TARGET: 玩家名字

示例：
SAY: 我注意到 {suspect} 总是引导我们避开不好的队伍。他们可能是梅林。
TARGET: {example_target}

可选目标：{targets_list}
你的回答："""


def _lady_of_lake_instructions(
    player: Player, player_names: List[str], prior_holders: Optional[List[str]] = None
) -> str:
    excluded = {player.name, *(prior_holders or [])}
    targets = [name for name in player_names if name not in excluded]
    targets_list = "、".join(targets)

    return f"""=== 你的任务 ===
你持有湖中夫人！选择一个人来调查。
你将秘密得知他们是正义方还是邪恶方。

格式：
SAY: [简短说明你选择的理由]
INSPECT: 玩家名字

示例：
SAY: 我想调查 {targets[0] if targets else "某人"}——他们的投票一直不一致。
INSPECT: {targets[0] if targets else "未知"}

可选目标：{targets_list}
你的回答："""
