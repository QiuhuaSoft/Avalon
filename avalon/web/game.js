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

const api = (path, options = {}) => fetch(path, options).then(async (res) => {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
});

const $ = (id) => document.getElementById(id);
const params = new URLSearchParams(window.location.search);

let playerToken = params.get("token") || localStorage.getItem("avalon_player_token") || "";
let playerId = params.get("player_id") || localStorage.getItem("avalon_player_id") || "";

const playerNameEl = $("playerName");
const roleRevealEl = $("roleReveal");
const phaseValueEl = $("phaseValue");
const questValueEl = $("questValue");
const playerTableEl = $("playerTable");
const chatLogEl = $("chatLog");
const actionPanelEl = $("actionPanel");
const privateIntelEl = $("privateIntel");
const botStatusEl = $("botStatus");
const actionHintEl = $("actionHint");
const proposalLeaderEl = $("proposalLeader");
const proposalHammerEl = $("proposalHammer");
const proposalTeamEl = $("proposalTeam");
const proposalMatrixHeadEl = $("proposalMatrixHead");
const proposalMatrixBodyEl = $("proposalMatrixBody");
const proposalMatrixEmptyEl = $("proposalMatrixEmpty");

let lastChatCount = 0;
let cachedState = null;
let cachedPrivate = null;
let cachedEvents = [];
let teamDraftKey = "";
let teamDraft = [];
let lastRenderedPhase = null;
let lastTeamVotesCount = 0;
let lastQuestVotesCount = 0;
let lastProposalAttempts = 0;
let lastLeaderIndex = -1;

if (!playerId && !playerToken) {
  roleRevealEl.textContent = "请先选择座位。";
}

// Mirrors EVIL_ROLES in avalon/game.py; used only for the end-game reveal,
// where the server publishes every player's true role.
const EVIL_ROLE_NAMES = new Set([
  "刺客",
  "莫甘娜",
  "莫德雷德",
  "奥伯伦",
  "莫德雷德的爪牙",
]);

function tagDiv(text) {
  const div = document.createElement("div");
  div.className = "tag";
  div.textContent = text;
  return div;
}

function renderPlayerTable(visibility = [], ladyHolderId, revealPlayers = null) {
  playerTableEl.innerHTML = "";
  // After game over the server publishes true roles; show them instead of the
  // viewer's now-stale alignment hints.
  const revealRoleById = {};
  if (Array.isArray(revealPlayers)) {
    revealPlayers.forEach((p) => {
      if (p && p.role) revealRoleById[p.id] = p.role;
    });
  }
  visibility.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "player-card";
    const revealedRole = revealRoleById[entry.id];
    let tag;
    if (revealedRole) {
      if (EVIL_ROLE_NAMES.has(revealedRole)) card.classList.add("evil");
      else card.classList.add("good");
      if (revealedRole === "梅林") card.classList.add("merlin");
      tag = revealedRole;
    } else {
      if (entry.alignment_hint === "evil") card.classList.add("evil");
      if (entry.alignment_hint === "merlin_candidate") card.classList.add("merlin");
      tag = entry.alignment_hint === "evil"
        ? "邪恶"
        : entry.alignment_hint === "merlin_candidate"
          ? "梅林?"
          : "未知";
    }
    if (entry.id === ladyHolderId) card.appendChild(tagDiv("湖中夫人"));
    card.appendChild(tagDiv(tag));
    // Player names are attacker-controlled: any remote player picks their own
    // name. Build the node with textContent (never innerHTML) so a name like
    // "<img src=x onerror=...>" renders as inert text instead of executing in
    // the host's privileged (localhost) browser session.
    const name = document.createElement("strong");
    name.textContent = entry.name;
    card.appendChild(name);
    playerTableEl.appendChild(card);
  });
}

function renderChat(chat = [], players = []) {
  const lookup = Object.fromEntries(players.map((p) => [p.id, p.name]));
  if (chat.length === lastChatCount) return;
  chatLogEl.innerHTML = "";
  chat.forEach((msg) => {
    const item = document.createElement("div");
    item.className = "chat-item";
    const name = lookup[msg.player_id] || msg.player_id;
    item.textContent = `${name}: ${msg.message}`;
    chatLogEl.appendChild(item);
  });
  lastChatCount = chat.length;
}

function renderPrivateIntel(privateState) {
  if (!privateState || !privateState.role) {
    privateIntelEl.textContent = "暂无私人情报。";
    return;
  }
  const knowledge = [...(privateState.knowledge || []), ...(privateState.lady_knowledge || [])];
  privateIntelEl.textContent = knowledge.length ? knowledge.join("\n") : "无特殊情报。";
}

function renderRoleReveal(privateState) {
  if (!privateState || !privateState.role) {
    roleRevealEl.textContent = "等待游戏开始…";
    return;
  }
  roleRevealEl.textContent = `你的身份：${privateState.role}。阵营：${privateState.alignment === "loyal" ? "正义方" : privateState.alignment === "evil" ? "邪恶方" : privateState.alignment}。`;
}

function playerName(state, playerId) {
  if (!state || !state.players) return playerId;
  const player = state.players.find((entry) => entry.id === playerId);
  return player ? player.name : playerId;
}

function hammerText(state) {
  if (!state || !state.config) {
    return "—";
  }
  const attempt = Math.min(5, (state.proposal_attempts || 0) + 1);
  const rejections = Math.min(4, state.proposal_attempts || 0);
  const hammer = state.config.hammer_auto_approve;
  if (attempt >= 5) {
    // The fifth proposal of the round. With the hammer it auto-approves; with
    // the hammer off this is the last chance, and a rejection hands evil the
    // win (official five-rejection rule) — so surface those stakes rather than
    // a bare "Disabled", since that off-hammer mode is exactly when the
    // rejection count matters most.
    return hammer
      ? "第5次提议（锤子）- 自动通过"
      : "第5次提议 - 拒绝 = 邪恶方获胜";
  }
  const suffix = hammer ? "" : " (无锤子)";
  return `第${attempt}次提议 - ${rejections}/4次拒绝${suffix}`;
}

function renderProposalTracker(state) {
  if (!state) {
    proposalLeaderEl.textContent = "—";
    proposalHammerEl.textContent = "—";
    proposalTeamEl.textContent = "尚未提议队伍。";
    return;
  }

  const leader = state.players[state.leader_index];
  proposalLeaderEl.textContent = leader ? leader.name : "—";
  proposalHammerEl.textContent = hammerText(state);

  if (state.proposed_team && state.proposed_team.length) {
    const teamNames = state.proposed_team.map((id) => playerName(state, id)).join(", ");
    proposalTeamEl.textContent = `队伍：${teamNames}`;
    return;
  }

  if (state.phase === "team_proposal" && leader) {
    proposalTeamEl.textContent = `等待 ${leader.name} 提议队伍。`;
    return;
  }
  proposalTeamEl.textContent = "尚未提议队伍。";
}

function buildProposalRecords(events = []) {
  let quest = 1;
  let attempt = 1;
  let current = null;
  let activeMissionRecord = null;
  let serial = 0;
  const records = [];

  events.forEach((event) => {
    if (!event || !event.type) return;

    if (event.type === "game_created" || event.type === "game_started") {
      quest = 1;
      attempt = 1;
      current = null;
      activeMissionRecord = null;
      serial = 0;
      if (event.type === "game_created") {
        records.length = 0;
      }
      return;
    }

    if (event.type === "team_proposed") {
      serial += 1;
      current = {
        id: `proposal-${serial}`,
        quest,
        attempt,
        leaderId: event.payload?.leader_id || null,
        team: Array.isArray(event.payload?.team) ? [...event.payload.team] : [],
        votes: {},
        approvals: null,
        rejects: null,
        hammered: false,
        result: "pending",
        missionResolved: false,
        missionSucceeded: null,
        missionFails: null,
      };
      records.push(current);
      return;
    }

    if (event.type === "team_vote" && current) {
      current.votes[event.payload?.player_id] = !!event.payload?.approve;
      return;
    }

    if (event.type === "team_hammered" && current) {
      current.hammered = true;
      current.result = "approved";
      current.approvals = null;
      current.rejects = null;
      activeMissionRecord = current;
      attempt = 1;
      return;
    }

    if (event.type === "team_approved" && current) {
      current.result = "approved";
      current.approvals = event.payload?.approvals;
      current.rejects = event.payload?.rejects;
      activeMissionRecord = current;
      attempt = 1;
      return;
    }

    if (event.type === "team_rejected" && current) {
      current.result = "rejected";
      current.approvals = event.payload?.approvals;
      current.rejects = event.payload?.rejects;
      activeMissionRecord = null;
      attempt += 1;
      return;
    }

    if (event.type === "quest_resolved") {
      const resolvedRecord = activeMissionRecord || [...records].reverse().find((entry) => (
        entry.result === "approved" && !entry.missionResolved
      ));
      if (resolvedRecord) {
        resolvedRecord.missionResolved = true;
        resolvedRecord.missionSucceeded = !!event.payload?.succeeded;
        resolvedRecord.missionFails = Number.isInteger(event.payload?.fails)
          ? event.payload.fails
          : null;
      }
      quest += 1;
      attempt = 1;
      current = null;
      activeMissionRecord = null;
    }
  });

  return records;
}

function missionSummary(record) {
  if (record.result === "rejected") {
    return { text: "未执行", cls: "mission-muted" };
  }
  if (record.result === "pending") {
    return { text: "等待投票", cls: "mission-pending" };
  }
  if (!record.missionResolved) {
    return { text: "进行中", cls: "mission-pending" };
  }
  const fails = Number.isInteger(record.missionFails) ? record.missionFails : 0;
  const passes = Math.max(0, (record.team?.length || 0) - fails);
  if (record.missionSucceeded) {
    return { text: `成功 (${passes}过/${fails}否)`, cls: "mission-pass" };
  }
  return { text: `失败 (${passes}过/${fails}否)`, cls: "mission-fail" };
}

function renderProposalMatrix(state, events) {
  if (!proposalMatrixHeadEl || !proposalMatrixBodyEl || !proposalMatrixEmptyEl) return;
  if (!state) {
    proposalMatrixHeadEl.innerHTML = "";
    proposalMatrixBodyEl.innerHTML = "";
    proposalMatrixEmptyEl.classList.remove("hidden");
    proposalMatrixEmptyEl.textContent = "没有进行中的游戏。";
    return;
  }

  const records = buildProposalRecords(events);
  const playerOrder = state.players.map((entry) => entry.id);
  const playerIndex = Object.fromEntries(playerOrder.map((pid, idx) => [pid, idx]));

  proposalMatrixHeadEl.innerHTML = "";
  proposalMatrixBodyEl.innerHTML = "";

  const headRow = document.createElement("tr");
  [
    "任务",
    "提议",
    "队长",
    "队伍",
    "计票",
    ...playerOrder.map((pid, idx) => `${idx + 1}: ${playerName(state, pid)}`),
    "任务",
  ]
    .forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      headRow.appendChild(th);
    });
  proposalMatrixHeadEl.appendChild(headRow);

  if (!records.length) {
    proposalMatrixEmptyEl.classList.remove("hidden");
    proposalMatrixEmptyEl.textContent = "暂无队伍提议。";
    return;
  }

  proposalMatrixEmptyEl.classList.add("hidden");

  records.forEach((record) => {
    const tr = document.createElement("tr");
    tr.className = `proposal-row ${record.result}`;

    const appendCell = (text, cls = "") => {
      const td = document.createElement("td");
      if (cls) td.className = cls;
      td.textContent = text;
      tr.appendChild(td);
    };

    appendCell(String(record.quest));
    appendCell(String(record.attempt));
    appendCell(`👑 ${playerName(state, record.leaderId)}`, "leader-cell");
    const orderedTeam = [...record.team].sort((a, b) => {
      const ai = Number.isInteger(playerIndex[a]) ? playerIndex[a] : 999;
      const bi = Number.isInteger(playerIndex[b]) ? playerIndex[b] : 999;
      return ai - bi;
    });
    appendCell(orderedTeam.map((id) => playerName(state, id)).join(", "), "team-cell");

    if (typeof record.approvals === "number" && typeof record.rejects === "number") {
      appendCell(`${record.approvals}Y / ${record.rejects}N`);
    } else if (record.hammered) {
      appendCell("锤子");
    } else {
      appendCell("等待中");
    }

    playerOrder.forEach((pid) => {
      const vote = record.votes[pid];
      const isProposer = pid === record.leaderId;
      const proposerMark = isProposer ? "👑 " : "";
      if (vote === true) {
        appendCell(`${proposerMark}Y`, `vote-yes${isProposer ? " proposer-vote" : ""}`);
      } else if (vote === false) {
        appendCell(`${proposerMark}N`, `vote-no${isProposer ? " proposer-vote" : ""}`);
      } else {
        appendCell(`${proposerMark}-`, `vote-none${isProposer ? " proposer-vote" : ""}`);
      }
    });

    const mission = missionSummary(record);
    appendCell(mission.text, mission.cls);
    proposalMatrixBodyEl.appendChild(tr);
  });
}

function actionHint(text) {
  // Render a single hint line via textContent (never innerHTML) so any
  // interpolated player name stays inert text rather than active markup.
  actionPanelEl.innerHTML = "";
  const p = document.createElement("p");
  p.className = "hint";
  p.textContent = text;
  actionPanelEl.appendChild(p);
}

function describeOutcome(state) {
  // The server reveals roles at game over, so we can name how the game ended.
  const evilWon = state.winner === "evil";
  if (state.assassin_target) {
    const target = state.players.find((p) => p.id === state.assassin_target);
    const targetName = target ? target.name : state.assassin_target;
    if (target && target.role === "梅林") {
      return `刺客找到了梅林（${targetName}），为邪恶方赢得了胜利。`;
    }
    return `刺客刺杀了 ${targetName}，但那不是梅林——正义方保住了胜利。`;
  }
  if (evilWon) {
    if ((state.fail_count || 0) >= 3) {
      return "三个任务被破坏。邪恶方控制了卡美洛。";
    }
    return "一轮中五次提议被拒绝——邪恶方因僵局获胜。";
  }
  return "三个任务成功，梅林在刺客的追杀下幸存。正义方获胜。";
}

function renderEndgameReveal(state) {
  // Climactic end-of-game reveal: announce the winner, how it happened, and
  // every player's true role. Names are attacker-controlled, so every name is
  // written with textContent (never innerHTML) — same rule as the rest of the
  // game view, since the host reads this page with localhost privileges.
  actionPanelEl.innerHTML = "";
  const evilWon = state.winner === "evil";

  const headline = document.createElement("p");
  headline.className = `reveal-headline ${evilWon ? "evil" : "good"}`;
  headline.textContent = evilWon ? "邪恶方获胜" : "正义方获胜";
  actionPanelEl.appendChild(headline);

  const outcome = document.createElement("p");
  outcome.className = "hint";
  outcome.textContent = describeOutcome(state);
  actionPanelEl.appendChild(outcome);

  const grid = document.createElement("div");
  grid.className = "reveal-grid";
  state.players.forEach((p) => {
    const row = document.createElement("div");
    const evil = EVIL_ROLE_NAMES.has(p.role);
    row.className = `reveal-row ${p.role ? (evil ? "evil" : "good") : ""}`;

    const name = document.createElement("strong");
    name.textContent = p.name;
    row.appendChild(name);

    const role = document.createElement("span");
    role.className = "reveal-role";
    role.textContent = p.role || "未知";
    row.appendChild(role);

    grid.appendChild(row);
  });
  actionPanelEl.appendChild(grid);
}

function renderActionMenu(state, privateState) {
  actionPanelEl.innerHTML = "";
  if (!state) {
    actionHint("没有进行中的游戏。");
    return;
  }

  const player = state.players.find((p) => p.id === playerId);
  if (!player) {
    actionHint("未找到玩家。请返回 /play。");
    return;
  }

  const phase = state.phase;
  const leader = state.players[state.leader_index];
  if (phase !== "team_proposal" || leader.id !== playerId) {
    teamDraftKey = "";
    teamDraft = [];
  }

  const addButton = (label, handler, ghost = false) => {
    const btn = document.createElement("button");
    btn.textContent = label;
    if (ghost) btn.classList.add("ghost");
    btn.addEventListener("click", async () => {
      actionHintEl.textContent = "";
      try {
        await handler();
      } catch (err) {
        actionHintEl.textContent = err.message || "操作失败。";
      }
    });
    actionPanelEl.appendChild(btn);
  };

  const addTeamPicker = (size) => {
    const draftKey = `${state.id}:${state.quest_number}:${state.proposal_attempts}:${leader.id}:${size}`;
    if (teamDraftKey !== draftKey) {
      teamDraftKey = draftKey;
      teamDraft = [];
    }

    const selector = document.createElement("div");
    selector.className = "stack";
    const info = document.createElement("p");
    info.className = "hint";
    info.textContent = `选择 ${size} 名玩家（可以包含自己）。`;
    selector.appendChild(info);

    const selects = [];
    const playerIds = state.players.map((p) => p.id);
    const used = new Set();
    for (let i = 0; i < size; i += 1) {
      const select = document.createElement("select");
      state.players.forEach((p) => {
        const opt = document.createElement("option");
        opt.value = p.id;
        opt.textContent = p.name;
        select.appendChild(opt);
      });

      const draftedId = teamDraft[i];
      let defaultId = "";
      if (draftedId && playerIds.includes(draftedId) && !used.has(draftedId)) {
        defaultId = draftedId;
      } else {
        defaultId = playerIds.find((id) => !used.has(id)) || playerIds[0] || "";
      }
      if (defaultId) {
        select.value = defaultId;
        used.add(defaultId);
      }
      selects.push(select);
      selector.appendChild(select);
    }

    const syncDraft = () => {
      teamDraft = selects.map((s) => s.value);
    };

    const syncSelections = () => {
      const chosen = new Set(selects.map((s) => s.value));
      selects.forEach((select) => {
        Array.from(select.options).forEach((opt) => {
          if (opt.value === select.value) {
            opt.disabled = false;
            return;
          }
          opt.disabled = chosen.has(opt.value);
        });
      });
    };
    selects.forEach((select) => {
      select.addEventListener("change", () => {
        syncDraft();
        syncSelections();
      });
    });
    syncDraft();
    syncSelections();

    addButton("提交队伍", async () => {
      const team = selects.map((s) => s.value);
      if (new Set(team).size !== team.length) {
        throw new Error("队伍不能包含重复玩家。");
      }
      if (team.length !== size) {
        throw new Error("队伍人数不正确。");
      }
      await submitAction("propose_team", { team });
    });
    actionPanelEl.appendChild(selector);
  };

  if (phase === "team_proposal") {
    if (leader.id !== playerId) {
      actionHint(`等待 ${leader.name} 提议队伍。`);
      return;
    }
    const size = teamSize(state);
    addTeamPicker(size);
    return;
  }

  if (phase === "team_vote") {
    if (state.team_votes && state.team_votes[playerId] !== undefined) {
      actionHint("已投票。等待其他人。");
      return;
    }
    addButton("同意组队", () => submitAction("vote_team", { approve: true }));
    addButton("拒绝组队", () => submitAction("vote_team", { approve: false }), true);
    return;
  }

  if (phase === "quest") {
    if (!state.proposed_team.includes(playerId)) {
      actionHint("任务进行中。你不在队伍中。");
      return;
    }
    if (state.quest_votes && state.quest_votes[playerId] !== undefined) {
      actionHint("已投票。");
      return;
    }
    addButton("任务成功", () => submitAction("quest_vote", { success: true }));
    addButton("任务失败", () => submitAction("quest_vote", { success: false }), true);
    return;
  }

  if (phase === "lady_of_lake") {
    if (state.lady_holder_id !== playerId) {
      actionHint("等待湖中夫人。");
      return;
    }
    const select = document.createElement("select");
    state.players.forEach((p) => {
      if (p.id === playerId) return;
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      select.appendChild(opt);
    });
    actionPanelEl.appendChild(select);
    addButton("使用湖中夫人", () => submitAction("lady_peek", { target_id: select.value }));
    return;
  }

  if (phase === "assassination") {
    if (privateState.role !== "刺客") {
      actionHint("等待刺客。");
      return;
    }
    // The assassin and their known evil teammates can never be Merlin, so
    // offering them only invites an accidental game-losing shot (the engine
    // rejects these targets too). Oberon stays in the list: it reads as
    // "unknown" to the assassin, and hiding it would leak that alignment.
    const knownEvil = new Set(
      (privateState.visibility || [])
        .filter((entry) => entry.alignment_hint === "evil")
        .map((entry) => entry.id),
    );
    const select = document.createElement("select");
    state.players.forEach((p) => {
      if (p.id === playerId || knownEvil.has(p.id)) return;
      const opt = document.createElement("option");
      opt.value = p.id;
      opt.textContent = p.name;
      select.appendChild(opt);
    });
    actionPanelEl.appendChild(select);
    addButton("执行刺杀", () => submitAction("assassinate", { target_id: select.value }));
    return;
  }

  if (phase === "game_over") {
    renderEndgameReveal(state);
    return;
  }

  actionHint("等待下一阶段。");
}

function teamSize(state) {
  const sizes = {
    5: [2, 3, 2, 3, 3],
    6: [2, 3, 4, 3, 4],
    7: [2, 3, 3, 4, 4],
    8: [3, 4, 4, 5, 5],
    9: [3, 4, 4, 5, 5],
    10: [3, 4, 4, 5, 5],
  };
  return sizes[state.config.player_count][state.quest_number - 1];
}

async function submitAction(actionType, payload) {
  await api("/game/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token: playerToken || undefined, player_id: playerId, action_type: actionType, payload }),
  });
}

$("sendChat").addEventListener("click", async () => {
  const message = $("chatMessage").value.trim();
  if (!message) return;
  await submitAction("chat", { message });
  $("chatMessage").value = "";
});

async function refresh() {
  try {
    if (playerToken) {
      localStorage.setItem("avalon_player_token", playerToken);
    }
    const [publicState, privateState, eventsPayload] = await Promise.all([
      api("/game/state"),
      playerToken
        ? api(`/game/state?token=${playerToken}`)
        : playerId
          ? api(`/game/state?player_id=${playerId}`)
          : Promise.resolve(null),
      api("/game/events").catch(() => ({ events: cachedEvents })),
    ]);
    cachedState = publicState.state;
    cachedPrivate = privateState;
    if (eventsPayload && Array.isArray(eventsPayload.events)) {
      cachedEvents = eventsPayload.events;
    }
    const pending = privateState?.pending || publicState?.pending || null;
    if (cachedPrivate?.player_id) {
      playerId = cachedPrivate.player_id;
      localStorage.setItem("avalon_player_id", playerId);
    }

    if (!cachedState) {
      roleRevealEl.textContent = "等待房主创建游戏。";
      renderProposalTracker(null);
      renderProposalMatrix(null, []);
      lastRenderedPhase = null;
      lastTeamVotesCount = 0;
      lastQuestVotesCount = 0;
      lastProposalAttempts = 0;
      lastLeaderIndex = -1;
      return;
    }

    if (cachedState.phase === "lobby") {
      lastRenderedPhase = null;
      lastTeamVotesCount = 0;
      lastQuestVotesCount = 0;
      lastProposalAttempts = 0;
      lastLeaderIndex = -1;
      window.location.href = "/lobby";
      return;
    }

    if (cachedState) {
      phaseValueEl.textContent = phaseDisplayName(cachedState.phase);
      questValueEl.textContent = cachedState.quest_number;
      const player = cachedState.players.find((p) => p.id === playerId);
      playerNameEl.textContent = player ? player.name : "玩家";
      renderChat(cachedState.chat || [], cachedState.players || []);
      renderProposalTracker(cachedState);
      renderProposalMatrix(cachedState, cachedEvents);
    }
    if (cachedPrivate) {
      renderRoleReveal(cachedPrivate);
      renderPrivateIntel(cachedPrivate);
      // At game over the public state carries every true role; pass it so the
      // table shows the reveal instead of the viewer's stale hints.
      const revealPlayers = cachedState?.phase === "game_over" ? cachedState.players : null;
      renderPlayerTable(cachedPrivate.visibility || [], cachedState?.lady_holder_id, revealPlayers);
    }
    // Use the private snapshot when available: the public state redacts the
    // viewer's own pending votes, which the action menu needs to detect.
    // Only re-render the action menu when critical state changes to avoid
    // resetting user selections in dropdowns (e.g., team picker).
    const stateForMenu = cachedPrivate?.state || cachedState;
    const currentPhase = stateForMenu?.phase;
    const currentTeamVotesCount = Object.keys(stateForMenu?.team_votes || {}).length;
    const currentQuestVotesCount = Object.keys(stateForMenu?.quest_votes || {}).length;
    const currentProposalAttempts = stateForMenu?.proposal_attempts || 0;
    const currentLeaderIndex = stateForMenu?.leader_index ?? -1;
    const phaseChanged = currentPhase !== lastRenderedPhase;
    const votesChanged = currentTeamVotesCount !== lastTeamVotesCount ||
                         currentQuestVotesCount !== lastQuestVotesCount;
    const proposalChanged = currentProposalAttempts !== lastProposalAttempts ||
                            currentLeaderIndex !== lastLeaderIndex;

    if (phaseChanged || votesChanged || proposalChanged) {
      lastRenderedPhase = currentPhase;
      lastTeamVotesCount = currentTeamVotesCount;
      lastQuestVotesCount = currentQuestVotesCount;
      lastProposalAttempts = currentProposalAttempts;
      lastLeaderIndex = currentLeaderIndex;
      renderActionMenu(cachedPrivate?.state || cachedState, cachedPrivate || {});
    }
    if (pending && pending.bot && pending.bot.length && !(pending.human && pending.human.length)) {
      botStatusEl.textContent = `机器人思考中…（${pending.bot.length} 个待处理）`;
      botStatusEl.classList.remove("hidden");
    } else {
      botStatusEl.textContent = "";
      botStatusEl.classList.add("hidden");
    }
  } catch (err) {
    roleRevealEl.textContent = "无法连接服务器。";
  }
}

let pollTimer = null;

refresh();
pollTimer = setInterval(() => {
  if (cachedState && cachedState.phase === "game_over") {
    clearInterval(pollTimer);
    pollTimer = null;
    return;
  }
  refresh();
}, 1500);
