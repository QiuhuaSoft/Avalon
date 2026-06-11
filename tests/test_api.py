"""HTTP-layer tests: localhost detection, token auth, and ballot secrecy.

TestClient instances are deliberately not used as context managers: that skips
the startup hook, so the background bot loop never runs and every state change
in these tests is driven by an explicit request.
"""

from fastapi.testclient import TestClient

from avalon import api

local = TestClient(api.app, client=("127.0.0.1", 50001))
remote = TestClient(api.app, client=("198.51.100.7", 50002))

ROSTER = [{"id": f"h{i}", "name": f"Human {i}", "is_bot": False} for i in range(1, 6)]


def create_game(**overrides):
    payload = {"players": ROSTER, "hammer_auto_approve": True, "lady_of_lake": False}
    payload.update(overrides)
    response = local.post("/game/new", json=payload)
    assert response.status_code == 200
    return response.json()


def start_game():
    response = local.post("/game/start")
    assert response.status_code == 200
    return response.json()["state"]


def act(player_id, action_type, payload):
    response = local.post(
        "/game/action",
        json={"player_id": player_id, "action_type": action_type, "payload": payload},
    )
    assert response.status_code == 200, response.text
    return response.json()["state"]


def public_state():
    response = local.get("/game/state")
    assert response.status_code == 200
    return response.json()["state"]


def private_state(player_id):
    response = local.get(f"/game/state?player_id={player_id}")
    assert response.status_code == 200
    return response.json()["state"]


def event_log():
    response = local.get("/game/events")
    assert response.status_code == 200
    return [event["type"] for event in response.json()["events"]]


def test_localhost_only_endpoints_reject_remote_clients():
    create_game()
    assert remote.post("/game/new", json={"players": ROSTER}).status_code == 403
    assert remote.post("/game/start").status_code == 403
    assert remote.get("/game/host_token").status_code == 403
    assert remote.get("/game/pending_bots").status_code == 403
    assert remote.get("/game/bot_context/b1").status_code == 403
    assert remote.post("/tunnel/start").status_code == 403
    assert remote.get("/tunnel/status").status_code == 403
    assert remote.post("/tunnel/stop").status_code == 403
    assert remote.post("/game/players/add", json={"is_bot": True}).status_code == 403
    assert (
        remote.post("/game/players/remove", json={"player_id": "h5"}).status_code == 403
    )
    assert remote.post("/game/players/reset", json={"player_id": "h1"}).status_code == 403
    assert remote.post("/game/players/remove_last_human").status_code == 403


def test_proxied_loopback_requests_are_treated_as_remote():
    """cloudflared connects from 127.0.0.1, so forwarding headers must matter."""
    create_game()
    proxy_headers = [
        {"X-Forwarded-For": "203.0.113.9"},
        {"CF-Connecting-IP": "203.0.113.9"},
        {"X-Real-IP": "203.0.113.9"},
        {"Forwarded": "for=203.0.113.9"},
    ]
    for headers in proxy_headers:
        response = local.get("/game/host_token", headers=headers)
        assert response.status_code == 403, f"{headers} should mark request remote"
        response = local.post("/game/new", json={"players": ROSTER}, headers=headers)
        assert response.status_code == 403


def test_host_token_available_to_genuine_localhost():
    created = create_game()
    response = local.get("/game/host_token")
    assert response.status_code == 200
    assert response.json()["host_token"] == created["host_token"]


def test_host_token_authorizes_remote_player_management():
    host_token = create_game()["host_token"]
    response = remote.post(
        "/game/players/add", json={"is_bot": True, "host_token": host_token}
    )
    assert response.status_code == 200
    assert len(response.json()["state"]["players"]) == 6


def test_remote_actions_require_a_valid_token():
    create_game()
    joined = local.post("/game/players/join", json={"name": "Tester"}).json()
    player_id, token = joined["player_id"], joined["token"]

    no_token = remote.post(
        "/game/action",
        json={"player_id": player_id, "action_type": "chat", "payload": {"message": "hi"}},
    )
    assert no_token.status_code == 403

    bogus = remote.post(
        "/game/action",
        json={"token": "not-a-token", "action_type": "chat", "payload": {"message": "hi"}},
    )
    assert bogus.status_code == 400

    with_token = remote.post(
        "/game/action",
        json={"token": token, "action_type": "chat", "payload": {"message": "hi"}},
    )
    assert with_token.status_code == 200

    assert remote.get(f"/game/state?player_id={player_id}").status_code == 403
    private = remote.get(f"/game/state?token={token}")
    assert private.status_code == 200
    assert private.json()["player_id"] == player_id


def test_bot_context_requires_external_mode():
    create_game()
    response = local.get("/game/bot_context/h1")
    assert response.status_code == 400
    assert "external bot mode" in response.json()["error"]


def test_tunnel_status_reports_without_starting_anything():
    response = local.get("/tunnel/status")
    assert response.status_code == 200
    assert response.json()["tunnel"]["running"] is False


def test_ballots_stay_secret_until_resolved():
    create_game()
    state = start_game()
    players = [p["id"] for p in state["players"]]
    leader = players[state["leader_index"]]
    second = players[(state["leader_index"] + 1) % 5]
    rest = [pid for pid in players if pid not in (leader, second)]

    act(leader, "propose_team", {"team": [leader, second]})
    assert event_log().count("team_vote") == 0

    # Two ballots in: nothing visible publicly, voters see only their own.
    act(leader, "vote_team", {"approve": True})
    act(second, "vote_team", {"approve": True})
    assert event_log().count("team_vote") == 0
    assert public_state()["team_votes"] == {}
    assert private_state(leader)["team_votes"] == {leader: True}
    assert private_state(rest[0])["team_votes"] == {}

    # Resolution: 3 approve vs 2 reject. Ballots become public record.
    act(rest[0], "vote_team", {"approve": True})
    act(rest[1], "vote_team", {"approve": False})
    state = act(rest[2], "vote_team", {"approve": False})
    assert state["phase"] == "quest"
    log = event_log()
    assert log.count("team_vote") == 5
    assert log.index("team_approved") > log.index("team_proposed")
    assert len(public_state()["team_votes"]) == 5

    # Quest ballots never appear, individually or in the event log.
    act(leader, "quest_vote", {"success": True})
    assert public_state()["quest_votes"] == {}
    assert private_state(leader)["quest_votes"] == {leader: True}
    assert private_state(second)["quest_votes"] == {}
    act(second, "quest_vote", {"success": True})
    log = event_log()
    assert "quest_vote" not in log
    assert "quest_resolved" in log


def test_events_endpoint_is_public_for_spectators():
    create_game()
    response = remote.get("/game/events")
    assert response.status_code == 200
    assert "game_created" in [event["type"] for event in response.json()["events"]]


def test_public_state_never_includes_roles():
    create_game()
    start_game()
    assert all(p["role"] is None for p in public_state()["players"])


def test_lifespan_starts_and_stops_the_bot_loop_cleanly():
    with TestClient(api.app, client=("127.0.0.1", 50003)) as client:
        assert client.get("/game/state").status_code == 200
