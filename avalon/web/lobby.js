const api = (path, options = {}) => fetch(path, options).then(async (res) => {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
});

const $ = (id) => document.getElementById(id);
const phaseValueEl = $("phaseValue");
const seatCountEl = $("seatCount");
const playerListEl = $("playerList");
const playerNameInput = $("playerNameInput");
const joinBtn = $("joinBtn");
const readyBtn = $("readyBtn");
const lobbyHintEl = $("lobbyHint");
const seatInfoEl = $("seatInfo");
const personalLinkCardEl = $("personalLinkCard");
const personalLinkTextEl = $("personalLinkText");
const hostControlsEl = $("hostControls");
const hostSlotListEl = $("hostSlotList");
const hostAddHuman = $("hostAddHuman");
const hostRemoveHuman = $("hostRemoveHuman");

const params = new URLSearchParams(window.location.search);
const urlHostToken = params.get("host_token") || "";
const urlPlayerToken = params.get("token") || "";

let playerId = localStorage.getItem("avalon_player_id") || "";
let playerToken = urlPlayerToken || localStorage.getItem("avalon_player_token") || "";
let gameId = localStorage.getItem("avalon_game_id") || "";
let hostToken = urlHostToken || localStorage.getItem("avalon_host_token") || "";
let playerName = localStorage.getItem("avalon_player_name") || "";
let adminToken = localStorage.getItem("avalon_admin_token") || "";

if (urlHostToken) {
  localStorage.setItem("avalon_host_token", urlHostToken);
}
if (urlPlayerToken) {
  localStorage.setItem("avalon_player_token", urlPlayerToken);
}

// Host controls are visible only to admins (logged in with password) or localhost
const isHost = Boolean(adminToken) || ["localhost", "127.0.0.1"].includes(window.location.hostname);

// Pre-fill name input from localStorage
if (playerName) {
  playerNameInput.value = playerName;
}

function updatePersonalLink() {
  if (!playerToken) {
    personalLinkCardEl.classList.add("hidden");
    personalLinkTextEl.textContent = "—";
    return;
  }
  const url = new URL(window.location.href);
  url.searchParams.set("token", playerToken);
  if (hostToken) {
    url.searchParams.set("host_token", hostToken);
  } else {
    url.searchParams.delete("host_token");
  }
  personalLinkTextEl.textContent = url.toString();
  personalLinkCardEl.classList.remove("hidden");
}

function renderPlayers(players) {
  playerListEl.innerHTML = "";
  players.filter((p) => !p.is_bot).forEach((player) => {
    const row = document.createElement("div");
    row.className = "slot-row";
    const tag = document.createElement("span");
    tag.className = "slot-tag";
    tag.textContent = player.ready ? "已准备" : player.claimed ? "已加入" : "空位";
    const name = document.createElement("div");
    name.textContent = player.name;
    row.appendChild(tag);
    row.appendChild(name);
    playerListEl.appendChild(row);
  });
}

function renderHostSlots(players) {
  hostSlotListEl.innerHTML = "";
  players
    .filter((p) => !p.is_bot)
    .forEach((player) => {
      const row = document.createElement("div");
      row.className = "slot-row";
      const tag = document.createElement("span");
      tag.className = "slot-tag";
      tag.textContent = player.ready ? "已准备" : player.claimed ? "已加入" : "空位";
      const nameInput = document.createElement("input");
      nameInput.maxLength = 60; // mirrors the server-side MAX_NAME_LENGTH cap in game.py
      nameInput.value = player.name;
      const saveBtn = document.createElement("button");
      saveBtn.className = "ghost";
      saveBtn.textContent = "改名";
      saveBtn.addEventListener("click", async () => {
        await api("/game/players/rename", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_id: player.id, name: nameInput.value.trim() || player.name, host_token: hostToken || undefined }),
        });
        await refresh();
      });
      const kickBtn = document.createElement("button");
      kickBtn.className = "ghost";
      kickBtn.textContent = "踢出";
      kickBtn.addEventListener("click", async () => {
        await api("/game/players/reset", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ player_id: player.id, host_token: hostToken || undefined }),
        });
        await refresh();
      });
      row.appendChild(tag);
      row.appendChild(nameInput);
      row.appendChild(saveBtn);
      row.appendChild(kickBtn);
      hostSlotListEl.appendChild(row);
    });
}

async function joinGame() {
  const name = playerNameInput.value.trim();
  if (!name) {
    lobbyHintEl.textContent = "请先输入你的名字。";
    return;
  }

  // Save name to localStorage
  localStorage.setItem("avalon_player_name", name);
  playerName = name;

  // If already joined, rename instead of joining again
  if (playerId) {
    try {
      await api("/game/players/rename", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          player_id: playerId,
          name,
          host_token: hostToken || undefined,
          token: playerToken || undefined,
        }),
      });
      seatInfoEl.textContent = `座位已认领：${name}。`;
      lobbyHintEl.textContent = "名字已更新。";
      await refresh();
    } catch (err) {
      lobbyHintEl.textContent = "改名失败：" + err.message;
    }
    return; // Don't try to join again if already joined
  }

  try {
    const result = await api("/game/players/join", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name }),
    });
    playerId = result.player_id;
    playerToken = result.token || "";
    if (playerToken) {
      localStorage.setItem("avalon_player_token", playerToken);
      const url = new URL(window.location.href);
      url.searchParams.set("token", playerToken);
      if (hostToken) {
        url.searchParams.set("host_token", hostToken);
      } else {
        url.searchParams.delete("host_token");
      }
      window.history.replaceState({}, "", url);
      updatePersonalLink();
    } else {
      personalLinkCardEl.classList.add("hidden");
    }
    if (result.state?.id) {
      gameId = result.state.id;
      localStorage.setItem("avalon_game_id", gameId);
    }
    localStorage.setItem("avalon_player_id", playerId);
    seatInfoEl.textContent = `座位已认领：${name}。`;
    lobbyHintEl.textContent = "已入座。准备好后点击'准备'。";
    await refresh();
  } catch (err) {
    lobbyHintEl.textContent = err.message;
  }
}

async function readyUp() {
  if (!playerId) {
    lobbyHintEl.textContent = "请先加入游戏。";
    return;
  }
  if (!playerToken && !isHost) {
    lobbyHintEl.textContent = "缺少玩家令牌。请重新加入大厅链接。";
    return;
  }
  try {
    await api("/game/players/ready", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ token: playerToken || undefined, player_id: playerId, ready: true }),
    });
    lobbyHintEl.textContent = "已准备。等待其他人…";
    await refresh();
  } catch (err) {
    lobbyHintEl.textContent = err.message;
  }
}

async function refresh() {
  try {
    const state = await api("/game/state");
    if (!state.state) {
      lobbyHintEl.textContent = "等待房主创建游戏。";
      return;
    }
    if (playerId && !playerToken && !isHost) {
      playerId = "";
      localStorage.removeItem("avalon_player_id");
      lobbyHintEl.textContent = "缺少玩家令牌。请点击'加入游戏'。";
    }
    if (state.state.id && state.state.id !== gameId) {
      gameId = state.state.id;
      localStorage.setItem("avalon_game_id", gameId);
      playerId = "";
      playerToken = "";
      hostToken = "";
      localStorage.removeItem("avalon_player_id");
      localStorage.removeItem("avalon_player_token");
      localStorage.removeItem("avalon_host_token");
    }
    const players = state.state.players || [];
    phaseValueEl.textContent = state.state.phase;
    seatCountEl.textContent = players.filter((p) => !p.is_bot).length;
    renderPlayers(players);
    if (isHost) {
      hostControlsEl.classList.remove("hidden");
      renderHostSlots(players);
    }
    const seat = players.find((p) => p.id === playerId);
    if (seat) {
      seatInfoEl.textContent = `座位：${seat.name}。状态：${seat.ready ? "已准备" : "已加入"}。`;
    }
    updatePersonalLink();
    if (playerId && state.state.started) {
      if (playerToken) {
        window.location.href = `/game?token=${playerToken}`;
      } else if (isHost) {
        window.location.href = `/game?player_id=${playerId}`;
      }
    }
  } catch (err) {
    lobbyHintEl.textContent = err.message;
  }
}

joinBtn.addEventListener("click", joinGame);
readyBtn.addEventListener("click", readyUp);

if (isHost) {
  hostAddHuman.addEventListener("click", async () => {
    await api("/game/players/add", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ is_bot: false, host_token: hostToken || undefined }),
    });
    await refresh();
  });
  hostRemoveHuman.addEventListener("click", async () => {
    const path = hostToken ? `/game/players/remove_last_human?host_token=${encodeURIComponent(hostToken)}` : "/game/players/remove_last_human";
    await api(path, { method: "POST" });
    await refresh();
  });
}

refresh();
setInterval(refresh, 1500);

// Auto-join for host if they have a saved name and aren't already joined
if (isHost && playerName && !playerId) {
  joinGame();
}
