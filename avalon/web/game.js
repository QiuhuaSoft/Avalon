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

if (!playerId && !playerToken) {
  roleRevealEl.textContent = "Pick a seat first.";
}

function renderPlayerTable(visibility = [], ladyHolderId) {
  playerTableEl.innerHTML = "";
  visibility.forEach((entry) => {
    const card = document.createElement("div");
    card.className = "player-card";
    if (entry.alignment_hint === "evil") card.classList.add("evil");
    if (entry.alignment_hint === "merlin_candidate") card.classList.add("merlin");
    const tag = entry.alignment_hint === "evil"
      ? "Evil"
      : entry.alignment_hint === "merlin_candidate"
        ? "Merlin?"
        : "Unknown";
    const ladyTag = entry.id === ladyHolderId ? "<div class=\"tag\">Lady</div>" : "";
    card.innerHTML = `${ladyTag}<div class=\"tag\">${tag}</div><strong>${entry.name}</strong>`;
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
    privateIntelEl.textContent = "No private intel yet.";
    return;
  }
  const knowledge = [...(privateState.knowledge || []), ...(privateState.lady_knowledge || [])];
  privateIntelEl.textContent = knowledge.length ? knowledge.join("\n") : "No special intel.";
}

function renderRoleReveal(privateState) {
  if (!privateState || !privateState.role) {
    roleRevealEl.textContent = "Waiting for game start…";
    return;
  }
  roleRevealEl.textContent = `You are ${privateState.role}. Alignment: ${privateState.alignment}.`;
}

function playerName(state, playerId) {
  if (!state || !state.players) return playerId;
  const player = state.players.find((entry) => entry.id === playerId);
  return player ? player.name : playerId;
}

function hammerText(state) {
  if (!state || !state.config || !state.config.hammer_auto_approve) {
    return "Disabled";
  }
  const attempt = Math.min(5, (state.proposal_attempts || 0) + 1);
  const rejections = Math.min(4, state.proposal_attempts || 0);
  if (attempt >= 5) {
    return `Proposal 5/5 (HAMMER) - auto-approve`;
  }
  return `Proposal ${attempt}/5 - ${rejections}/4 rejections`;
}

function renderProposalTracker(state) {
  if (!state) {
    proposalLeaderEl.textContent = "—";
    proposalHammerEl.textContent = "—";
    proposalTeamEl.textContent = "No proposed team yet.";
    return;
  }

  const leader = state.players[state.leader_index];
  proposalLeaderEl.textContent = leader ? leader.name : "—";
  proposalHammerEl.textContent = hammerText(state);

  if (state.proposed_team && state.proposed_team.length) {
    const teamNames = state.proposed_team.map((id) => playerName(state, id)).join(", ");
    proposalTeamEl.textContent = `Team: ${teamNames}`;
    return;
  }

  if (state.phase === "team_proposal" && leader) {
    proposalTeamEl.textContent = `Waiting for ${leader.name} to propose a team.`;
    return;
  }
  proposalTeamEl.textContent = "No proposed team yet.";
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
    return { text: "Not run", cls: "mission-muted" };
  }
  if (record.result === "pending") {
    return { text: "Pending vote", cls: "mission-pending" };
  }
  if (!record.missionResolved) {
    return { text: "In progress", cls: "mission-pending" };
  }
  const fails = Number.isInteger(record.missionFails) ? record.missionFails : 0;
  const passes = Math.max(0, (record.team?.length || 0) - fails);
  if (record.missionSucceeded) {
    return { text: `PASS (${passes}P/${fails}F)`, cls: "mission-pass" };
  }
  return { text: `FAIL (${passes}P/${fails}F)`, cls: "mission-fail" };
}

function renderProposalMatrix(state, events) {
  if (!proposalMatrixHeadEl || !proposalMatrixBodyEl || !proposalMatrixEmptyEl) return;
  if (!state) {
    proposalMatrixHeadEl.innerHTML = "";
    proposalMatrixBodyEl.innerHTML = "";
    proposalMatrixEmptyEl.classList.remove("hidden");
    proposalMatrixEmptyEl.textContent = "No active game.";
    return;
  }

  const records = buildProposalRecords(events);
  const playerOrder = state.players.map((entry) => entry.id);
  const playerIndex = Object.fromEntries(playerOrder.map((pid, idx) => [pid, idx]));

  proposalMatrixHeadEl.innerHTML = "";
  proposalMatrixBodyEl.innerHTML = "";

  const headRow = document.createElement("tr");
  [
    "Quest",
    "Prop",
    "Leader",
    "Team",
    "Tally",
    ...playerOrder.map((pid, idx) => `${idx + 1}: ${playerName(state, pid)}`),
    "Mission",
  ]
    .forEach((label) => {
      const th = document.createElement("th");
      th.textContent = label;
      headRow.appendChild(th);
    });
  proposalMatrixHeadEl.appendChild(headRow);

  if (!records.length) {
    proposalMatrixEmptyEl.classList.remove("hidden");
    proposalMatrixEmptyEl.textContent = "No team proposals yet.";
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
      appendCell("Hammer");
    } else {
      appendCell("Pending");
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

function renderActionMenu(state, privateState) {
  actionPanelEl.innerHTML = "";
  if (!state) {
    actionPanelEl.innerHTML = "<p class=\"hint\">No active game.</p>";
    return;
  }

  const player = state.players.find((p) => p.id === playerId);
  if (!player) {
    actionPanelEl.innerHTML = "<p class=\"hint\">Player not found. Return to /play.</p>";
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
        actionHintEl.textContent = err.message || "Action failed.";
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
    info.textContent = `Select ${size} players (including yourself if desired).`;
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

    addButton("Submit team", async () => {
      const team = selects.map((s) => s.value);
      if (new Set(team).size !== team.length) {
        throw new Error("Team cannot contain duplicate players.");
      }
      if (team.length !== size) {
        throw new Error("Invalid team size.");
      }
      await submitAction("propose_team", { team });
    });
    actionPanelEl.appendChild(selector);
  };

  if (phase === "team_proposal") {
    if (leader.id !== playerId) {
      actionPanelEl.innerHTML = `<p class=\"hint\">Waiting for ${leader.name} to propose a team.</p>`;
      return;
    }
    const size = teamSize(state);
    addTeamPicker(size);
    return;
  }

  if (phase === "team_vote") {
    if (state.team_votes && state.team_votes[playerId] !== undefined) {
      actionPanelEl.innerHTML = "<p class=\"hint\">Vote submitted. Waiting on others.</p>";
      return;
    }
    addButton("Approve team", () => submitAction("vote_team", { approve: true }));
    addButton("Reject team", () => submitAction("vote_team", { approve: false }), true);
    return;
  }

  if (phase === "quest") {
    if (!state.proposed_team.includes(playerId)) {
      actionPanelEl.innerHTML = "<p class=\"hint\">Quest in progress. You are not on the team.</p>";
      return;
    }
    if (state.quest_votes && state.quest_votes[playerId] !== undefined) {
      actionPanelEl.innerHTML = "<p class=\"hint\">Vote submitted.</p>";
      return;
    }
    addButton("Quest success", () => submitAction("quest_vote", { success: true }));
    addButton("Quest fail", () => submitAction("quest_vote", { success: false }), true);
    return;
  }

  if (phase === "lady_of_lake") {
    if (state.lady_holder_id !== playerId) {
      actionPanelEl.innerHTML = "<p class=\"hint\">Waiting for the Lady of the Lake.</p>";
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
    addButton("Use Lady of the Lake", () => submitAction("lady_peek", { target_id: select.value }));
    return;
  }

  if (phase === "assassination") {
    if (privateState.role !== "Assassin") {
      actionPanelEl.innerHTML = "<p class=\"hint\">Waiting for the assassin.</p>";
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
    addButton("Assassinate", () => submitAction("assassinate", { target_id: select.value }));
    return;
  }

  if (phase === "game_over") {
    actionPanelEl.innerHTML = `<p class=\"hint\">Game over. Winner: ${state.winner}</p>`;
    return;
  }

  actionPanelEl.innerHTML = "<p class=\"hint\">Waiting for next phase.</p>";
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
      roleRevealEl.textContent = "Waiting for host to create a game.";
      renderProposalTracker(null);
      renderProposalMatrix(null, []);
      return;
    }

    if (cachedState.phase === "lobby") {
      window.location.href = "/lobby";
      return;
    }

    if (cachedState) {
      phaseValueEl.textContent = cachedState.phase;
      questValueEl.textContent = cachedState.quest_number;
      const player = cachedState.players.find((p) => p.id === playerId);
      playerNameEl.textContent = player ? player.name : "Player";
      renderChat(cachedState.chat || [], cachedState.players || []);
      renderProposalTracker(cachedState);
      renderProposalMatrix(cachedState, cachedEvents);
    }
    if (cachedPrivate) {
      renderRoleReveal(cachedPrivate);
      renderPrivateIntel(cachedPrivate);
      renderPlayerTable(cachedPrivate.visibility || [], cachedState?.lady_holder_id);
    }
    // Use the private snapshot when available: the public state redacts the
    // viewer's own pending votes, which the action menu needs to detect.
    renderActionMenu(cachedPrivate?.state || cachedState, cachedPrivate || {});
    if (pending && pending.bot && pending.bot.length && !(pending.human && pending.human.length)) {
      botStatusEl.textContent = `Bots are thinking… (${pending.bot.length} pending)`;
      botStatusEl.classList.remove("hidden");
    } else {
      botStatusEl.textContent = "";
      botStatusEl.classList.add("hidden");
    }
  } catch (err) {
    roleRevealEl.textContent = "Unable to reach server.";
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
