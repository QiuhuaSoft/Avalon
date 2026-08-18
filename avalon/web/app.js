const api = (path, options = {}) => fetch(path, options).then(async (res) => {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
});

const $ = (id) => document.getElementById(id);

const stateEls = {
  serverStatus: $("serverStatus"),
  phaseValue: $("phaseValue"),
  publicState: $("publicState"),
  eventLog: $("eventLog"),
  privateState: $("privateState"),
  setupHint: $("setupHint"),
  actionHint: $("actionHint"),
};

const playerIdInput = $("playerId");

const formatJson = (obj) => JSON.stringify(obj, null, 2);

function phaseDisplayName(phase) {
  const names = {
    lobby: "大厅",
    team_proposal: "组队提议",
    team_vote: "投票表决",
    quest: "执行任务",
    lady_of_lake: "湖中夫人",
    assassination: "刺杀",
    game_over: "游戏结束",
  };
  return names[phase] || phase;
}

async function refreshState() {
  try {
    const state = await api("/game/state");
    stateEls.serverStatus.textContent = "在线";
    stateEls.phaseValue.textContent = state.state ? phaseDisplayName(state.state.phase) : "无游戏";
    stateEls.publicState.textContent = formatJson(state.state);
  } catch (err) {
    stateEls.serverStatus.textContent = "离线";
    stateEls.publicState.textContent = "无法连接服务器。";
  }
}

async function refreshEvents() {
  try {
    const events = await api("/game/events");
    stateEls.eventLog.textContent = formatJson(events.events);
  } catch (err) {
    stateEls.eventLog.textContent = "无法加载事件。";
  }
}

async function loadPrivate() {
  const playerId = playerIdInput.value.trim();
  if (!playerId) return;
  try {
    const privateState = await api(`/game/state?player_id=${playerId}`);
    stateEls.privateState.textContent = formatJson(privateState);
  } catch (err) {
    stateEls.privateState.textContent = err.message;
  }
}

function parseJson(text, fallback) {
  if (!text.trim()) return fallback;
  return JSON.parse(text);
}

$("createGame").addEventListener("click", async () => {
  try {
    const players = parseJson($("playersJson").value, []);
    const roles = parseJson($("rolesJson").value, null);
    const hammer = $("hammerRule").checked;
    const payload = { players, hammer_auto_approve: hammer };
    if (roles) payload.roles = roles;
    await api("/game/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    stateEls.setupHint.textContent = "游戏已创建。";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.setupHint.textContent = err.message;
  }
});

$("startGame").addEventListener("click", async () => {
  try {
    await api("/game/start", { method: "POST" });
    stateEls.setupHint.textContent = "游戏已开始。";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.setupHint.textContent = err.message;
  }
});

$("loadPrivate").addEventListener("click", loadPrivate);

$("sendChat").addEventListener("click", async () => {
  const playerId = playerIdInput.value.trim();
  const message = $("chatMessage").value.trim();
  if (!playerId || !message) return;
  try {
    await api("/game/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: playerId, action_type: "chat", payload: { message } }),
    });
    $("chatMessage").value = "";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.actionHint.textContent = err.message;
  }
});

$("proposeTeam").addEventListener("click", async () => {
  const playerId = playerIdInput.value.trim();
  const raw = $("teamIds").value.trim();
  const team = raw ? raw.split(",").map((id) => id.trim()).filter(Boolean) : [];
  try {
    await api("/game/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: playerId, action_type: "propose_team", payload: { team } }),
    });
    stateEls.actionHint.textContent = "队伍已提议。";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.actionHint.textContent = err.message;
  }
});

$("approveTeam").addEventListener("click", () => voteTeam(true));
$("rejectTeam").addEventListener("click", () => voteTeam(false));

async function voteTeam(approve) {
  const playerId = playerIdInput.value.trim();
  try {
    await api("/game/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: playerId, action_type: "vote_team", payload: { approve } }),
    });
    stateEls.actionHint.textContent = approve ? "队伍已通过。" : "队伍被拒绝。";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.actionHint.textContent = err.message;
  }
}

$("questSuccess").addEventListener("click", () => questVote(true));
$("questFail").addEventListener("click", () => questVote(false));

async function questVote(success) {
  const playerId = playerIdInput.value.trim();
  try {
    await api("/game/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: playerId, action_type: "quest_vote", payload: { success } }),
    });
    stateEls.actionHint.textContent = success ? "已提交任务成功。" : "已提交任务失败。";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.actionHint.textContent = err.message;
  }
}

$("assassinate").addEventListener("click", async () => {
  const playerId = playerIdInput.value.trim();
  const targetId = $("assassinTarget").value.trim();
  try {
    await api("/game/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ player_id: playerId, action_type: "assassinate", payload: { target_id: targetId } }),
    });
    stateEls.actionHint.textContent = "刺杀已提交。";
    await refreshState();
    await refreshEvents();
  } catch (err) {
    stateEls.actionHint.textContent = err.message;
  }
});

async function boot() {
  await refreshState();
  await refreshEvents();
  setInterval(refreshState, 2000);
  setInterval(refreshEvents, 4000);
}

boot();
