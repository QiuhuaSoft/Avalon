"""Heuristic-policy tests for the assassin's defer-to-human-teammate flow."""

from avalon.bot.policy import ASSASSIN_DEFER_MESSAGE, BotPolicy
from avalon.models import ChatMessage, GameConfig, GameState, Phase, Player, Role


def make_state(players, chat=None, phase=Phase.assassination):
    config = GameConfig(
        player_count=len(players),
        roles=[p.role for p in players],
        hammer_auto_approve=True,
        lady_of_lake=False,
    )
    return GameState(
        id="test-game",
        config=config,
        players=players,
        started=True,
        phase=phase,
        chat=list(chat or []),
    )


def assassination_players():
    """Bot assassin alongside one evil human; Pia is Merlin."""
    return [
        Player(id="b1", name="Hera", is_bot=True, role=Role.assassin),
        Player(id="h1", name="Mina", is_bot=False, role=Role.minion),
        Player(id="b2", name="Pia", is_bot=True, role=Role.merlin),
        Player(id="h2", name="Rook", is_bot=False, role=Role.percival),
        Player(id="b3", name="Al", is_bot=True, role=Role.loyal_servant),
    ]


def decide(state):
    policy = BotPolicy()
    assassin = next(p for p in state.players if p.role == Role.assassin)
    return policy.decide(state, assassin, [])


def defer_chat():
    return ChatMessage(player_id="b1", message=ASSASSIN_DEFER_MESSAGE)


def test_assassin_defers_once_then_waits():
    state = make_state(assassination_players())
    first = decide(state)
    assert first == {
        "action_type": "chat",
        "payload": {"message": ASSASSIN_DEFER_MESSAGE},
    }
    state.chat.append(defer_chat())
    second = decide(state)
    assert second == {"action_type": "wait"}


def test_assassin_follows_unambiguous_human_evil_guidance():
    state = make_state(
        assassination_players(),
        chat=[
            defer_chat(),
            ChatMessage(player_id="h1", message="I'm confident it's pia."),
        ],
    )
    action = decide(state)
    assert action == {"action_type": "assassinate", "payload": {"target_id": "b2"}}


def test_assassin_ignores_ambiguous_guidance():
    state = make_state(
        assassination_players(),
        chat=[
            defer_chat(),
            ChatMessage(player_id="h1", message="Either Pia or Rook could be Merlin."),
        ],
    )
    assert decide(state) == {"action_type": "wait"}


def test_assassin_ignores_guidance_from_good_players():
    state = make_state(
        assassination_players(),
        chat=[
            defer_chat(),
            ChatMessage(player_id="h2", message="It's definitely Pia!"),
        ],
    )
    assert decide(state) == {"action_type": "wait"}


def test_assassin_ignores_guidance_sent_before_deferring():
    state = make_state(
        assassination_players(),
        chat=[
            ChatMessage(player_id="h1", message="Pia for sure."),
            defer_chat(),
        ],
    )
    assert decide(state) == {"action_type": "wait"}


def test_latest_guidance_wins():
    state = make_state(
        assassination_players(),
        chat=[
            defer_chat(),
            ChatMessage(player_id="h1", message="Maybe Pia?"),
            ChatMessage(player_id="h1", message="No wait - Rook."),
        ],
    )
    action = decide(state)
    assert action == {"action_type": "assassinate", "payload": {"target_id": "h2"}}


def test_guidance_matches_whole_names_only():
    # "Al" must not match inside "Also"; only Pia is named.
    state = make_state(
        assassination_players(),
        chat=[
            defer_chat(),
            ChatMessage(player_id="h1", message="Also, Pia has been quiet all game."),
        ],
    )
    action = decide(state)
    assert action == {"action_type": "assassinate", "payload": {"target_id": "b2"}}


def test_guidance_naming_an_evil_player_is_ignored():
    # Evil teammates cannot be Merlin, so naming one is not a valid target.
    state = make_state(
        assassination_players(),
        chat=[
            defer_chat(),
            ChatMessage(player_id="h1", message="Hera should just pick."),
        ],
    )
    assert decide(state) == {"action_type": "wait"}


def test_assassin_without_human_evil_targets_good_players_immediately():
    players = [
        Player(id="b1", name="Astra", is_bot=True, role=Role.assassin),
        Player(id="b2", name="Brix", is_bot=True, role=Role.morgana),
        Player(id="b3", name="Caro", is_bot=True, role=Role.merlin),
        Player(id="b4", name="Dova", is_bot=True, role=Role.percival),
        Player(id="b5", name="Eryn", is_bot=True, role=Role.loyal_servant),
    ]
    state = make_state(players)
    for _ in range(25):
        action = decide(state)
        assert action["action_type"] == "assassinate"
        assert action["payload"]["target_id"] in {"b3", "b4", "b5"}
