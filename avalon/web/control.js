const api = (path, options = {}) => fetch(path, options).then(async (res) => {
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.error || res.statusText);
  }
  return res.json();
});

const $ = (id) => document.getElementById(id);
const roleGrid = $("roleGrid");
const humanCountEl = $("humanCount");
const botCountEl = $("botCount");
const totalCountEl = $("totalCount");
const joinLinksEl = $("joinLinks");
const serverStatusEl = $("serverStatus");
const phaseValueEl = $("phaseValue");
const publicStateEl = $("publicState");
const eventLogEl = $("eventLog");
const setupHintEl = $("setupHint");
const roleHintEl = $("roleHint");
const evilCountEl = $("evilCount");
const goodCountEl = $("goodCount");
const ladyToggle = $("ladyToggle");
const joinSection = $("joinSection");
const liveSection = $("liveSection");

const roleOptions = [
  { name: "派西维尔", alignment: "good", defaultOn: true },
  { name: "莫甘娜", alignment: "evil", defaultOn: true },
  { name: "莫德雷德", alignment: "evil", defaultOn: false },
  { name: "奥伯伦", alignment: "evil", defaultOn: false },
];

const mandatoryRoles = ["梅林", "刺客"];

let humanCount = 2;
let botCount = 3;
let evilCount = 2;
let gameCreated = false;
let gameStarted = false;
let publicBaseUrl = null;
let tunnelPolling = null;
let hostToken = localStorage.getItem("avalon_host_token") || "";
let adminToken = localStorage.getItem("avalon_admin_token") || "";
const loginModal = $("loginModal");
const loginPassword = $("loginPassword");
const loginBtn = $("loginBtn");
const loginHint = $("loginHint");
const adminStatusEl = $("adminStatus");
const adminStatusLabel = $("adminStatusLabel");

function defaultEvilCount(total) {
  if (total <= 6) return 2;
  if (total <= 9) return 3;
  return 4;
}

function updateTotals() {
  const total = humanCount + botCount;
  evilCount = Math.min(Math.max(1, evilCount), Math.max(1, total - 2));
  const goodCount = total - evilCount;
  humanCountEl.textContent = humanCount;
  botCountEl.textContent = botCount;
  totalCountEl.textContent = total;
  evilCountEl.textContent = evilCount;
  goodCountEl.textContent = goodCount;
  const valid = total >= 5 && total <= 10;
  totalCountEl.style.color = valid ? "inherit" : "#c75c2c";
}

function createRoleButton(role) {
  const button = document.createElement("button");
  button.className = "role-toggle";
  button.dataset.role = role.name;
  button.dataset.alignment = role.alignment;
  if (role.defaultOn) button.classList.add("active");
  button.textContent = role.name;
  button.addEventListener("click", () => {
    button.classList.toggle("active");
    enforcePercivalRule();
    updateRoleHint();
  });
  return button;
}

roleOptions.forEach((role) => roleGrid.appendChild(createRoleButton(role)));

ladyToggle.addEventListener("click", () => {
  ladyToggle.classList.toggle("active");
  updateRoleHint();
});

function adjustCount(kind, delta) {
  if (kind === "human") {
    humanCount = Math.max(1, humanCount + delta);
  } else {
    botCount = Math.max(0, botCount + delta);
  }
  const total = humanCount + botCount;
  evilCount = defaultEvilCount(total);
  updateTotals();
}

$("humanUp").addEventListener("click", () => adjustCount("human", 1));
$("humanDown").addEventListener("click", () => adjustCount("human", -1));
$("botUp").addEventListener("click", () => adjustCount("bot", 1));
$("botDown").addEventListener("click", () => adjustCount("bot", -1));
$("evilUp").addEventListener("click", () => {
  evilCount += 1;
  updateTotals();
});
$("evilDown").addEventListener("click", () => {
  evilCount -= 1;
  updateTotals();
});

function buildPlayers() {
  const players = [];
  for (let i = 1; i <= humanCount; i += 1) {
    players.push({ id: `h${i}`, name: `玩家${i}`, is_bot: false });
  }
  for (let i = 1; i <= botCount; i += 1) {
    players.push({ id: `b${i}`, name: `机器人${i}`, is_bot: true });
  }
  return players;
}

function buildRoles(totalPlayers) {
  const totalEvil = evilCount;
  const totalGood = totalPlayers - totalEvil;

  const goodRoles = ["梅林"];
  const evilRoles = ["刺客"];

  const activeRoles = [...roleGrid.querySelectorAll(".role-toggle.active[data-role]")].map(
    (btn) => btn.dataset.role
  );

  if (activeRoles.includes("派西维尔")) goodRoles.push("派西维尔");
  if (activeRoles.includes("莫甘娜")) evilRoles.push("莫甘娜");
  if (activeRoles.includes("莫德雷德")) evilRoles.push("莫德雷德");
  if (activeRoles.includes("奥伯伦")) evilRoles.push("奥伯伦");

  if (goodRoles.length > totalGood || evilRoles.length > totalEvil) return null;

  while (goodRoles.length < totalGood) goodRoles.push("忠臣");
  while (evilRoles.length < totalEvil) evilRoles.push("莫德雷德的爪牙");

  return [...goodRoles, ...evilRoles];
}

function createLinkCard(label, url) {
  const card = document.createElement("div");
  card.className = "link-card";
  const title = document.createElement("strong");
  title.textContent = label;
  const hint = document.createElement("p");
  hint.className = "hint";
  hint.style.wordBreak = "break-all";
  hint.textContent = url;
  const copyBtn = document.createElement("button");
  copyBtn.className = "ghost";
  copyBtn.textContent = "复制链接";
  copyBtn.style.marginTop = "8px";
  copyBtn.addEventListener("click", () => {
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(url).then(
        () => { copyBtn.textContent = "已复制"; setTimeout(() => copyBtn.textContent = "复制链接", 2000); },
        () => { fallbackCopy(url, copyBtn); }
      );
    } else {
      fallbackCopy(url, copyBtn);
    }
  });
  card.appendChild(title);
  card.appendChild(hint);
  card.appendChild(copyBtn);
  return card;
}

function fallbackCopy(text, btn) {
  const ta = document.createElement("textarea");
  ta.value = text;
  ta.style.position = "fixed";
  ta.style.opacity = "0";
  document.body.appendChild(ta);
  ta.select();
  try {
    document.execCommand("copy");
    btn.textContent = "已复制";
    setTimeout(() => btn.textContent = "复制链接", 2000);
  } catch (_) {
    btn.textContent = "复制失败";
    setTimeout(() => btn.textContent = "复制链接", 2000);
  }
  document.body.removeChild(ta);
}

function renderJoinLinks() {
  joinLinksEl.innerHTML = "";
  if (!publicBaseUrl) {
    joinLinksEl.textContent = "正在创建大厅链接…";
    return;
  }
  const url = `${publicBaseUrl}/play`;
  joinLinksEl.appendChild(createLinkCard("大厅链接（分享给玩家）", url));
  if (hostToken) {
    const hostUrl = `${publicBaseUrl}/play?host_token=${hostToken}`;
    joinLinksEl.appendChild(createLinkCard("房主大厅链接（管理员专用）", hostUrl));
  }
  setupHintEl.textContent = "大厅链接已就绪，请复制后分享给玩家。";
}

function updateVisibility() {
  joinSection.classList.toggle("hidden", !gameCreated);
  liveSection.classList.toggle("hidden", !gameStarted);
}

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
    serverStatusEl.textContent = "在线";
    phaseValueEl.textContent = state.state ? phaseDisplayName(state.state.phase) : "无游戏";
    publicStateEl.textContent = JSON.stringify(state.state, null, 2);
    if (state.state?.started) {
      gameStarted = true;
      updateVisibility();
    }
  } catch (err) {
    serverStatusEl.textContent = "离线";
    publicStateEl.textContent = "无法连接服务器。";
  }
}

async function refreshEvents() {
  try {
    const events = await api("/game/events");
    eventLogEl.textContent = JSON.stringify(events.events, null, 2);
  } catch (err) {
    eventLogEl.textContent = "无法加载事件。";
  }
}

async function ensureHostToken() {
  if (hostToken) return true;
  try {
    const params = adminToken ? `?admin_token=${encodeURIComponent(adminToken)}` : "";
    const hostResponse = await api(`/game/host_token${params}`);
    hostToken = hostResponse.host_token || "";
    if (hostToken) {
      localStorage.setItem("avalon_host_token", hostToken);
      return true;
    }
  } catch (err) {
    // Ignore; caller decides how to proceed.
  }
  return false;
}

function useCurrentOrigin() {
  publicBaseUrl = window.location.origin;
  setupHintEl.textContent = "大厅链接已就绪。";
  if (gameCreated) {
    renderJoinLinks();
  }
}

async function startTunnel() {
  try {
    await api("/tunnel/start", { method: "POST" });
    if (tunnelPolling) return;
    tunnelPolling = setInterval(async () => {
      try {
        const status = await api("/tunnel/status");
        if (status.tunnel.public_url) {
          publicBaseUrl = status.tunnel.public_url;
          await ensureHostToken();
          setupHintEl.textContent = "大厅链接已就绪。";
          clearInterval(tunnelPolling);
          tunnelPolling = null;
          if (gameCreated) {
            renderJoinLinks();
          }
          return;
        }
        if (status.tunnel.error) {
          clearInterval(tunnelPolling);
          tunnelPolling = null;
          useCurrentOrigin();
        }
      } catch (_) {
        clearInterval(tunnelPolling);
        tunnelPolling = null;
        useCurrentOrigin();
      }
    }, 1200);
  } catch (err) {
    // cloudflared not installed or failed to start — use server address directly
    useCurrentOrigin();
  }
}

$("createGame").addEventListener("click", async () => {
  try {
    const players = buildPlayers();
    const total = players.length;
    if (total < 5 || total > 10) {
      throw new Error("总人数必须在5到10之间。");
    }
    const roles = buildRoles(total);
    if (!roles) {
      throw new Error("角色选择不符合正义/邪恶方人数要求。");
    }
    const lady = ladyToggle.classList.contains("active");
    const requestBody = { players, roles, hammer_auto_approve: true, lady_of_lake: lady };
    if (adminToken) requestBody.admin_token = adminToken;
    const response = await api("/game/new", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(requestBody),
    });
    hostToken = response.host_token || "";
    if (hostToken) {
      localStorage.setItem("avalon_host_token", hostToken);
    }
    localStorage.removeItem("avalon_game_id");
    localStorage.removeItem("avalon_player_id");
    localStorage.removeItem("avalon_player_token");
    setupHintEl.textContent = "游戏已创建。正在启动隧道…";
    gameCreated = true;
    publicBaseUrl = null;
    renderJoinLinks();
    updateVisibility();
    await refreshState();
    await refreshEvents();
    await startTunnel();
  } catch (err) {
    setupHintEl.textContent = err.message;
  }
});

function enforcePercivalRule() {
  const percival = roleGrid.querySelector('[data-role="派西维尔"]');
  const morgana = roleGrid.querySelector('[data-role="莫甘娜"]');
  if (morgana.classList.contains("active") && !percival.classList.contains("active")) {
    percival.classList.add("active");
  }
}

// --- Admin authentication ---

async function checkAdminStatus() {
  try {
    const resp = await api("/admin/status");
    if (!resp.admin_required) {
      // Admin auth not needed, hide login modal and admin status
      loginModal.classList.add("hidden");
      return;
    }
    // Admin auth is required
    adminStatusLabel.style.display = "";
    adminStatusEl.style.display = "";
    if (adminToken) {
      // Already have a token, hide login modal
      loginModal.classList.add("hidden");
      adminStatusEl.textContent = "已登录";
    } else {
      // Show login modal
      loginModal.classList.remove("hidden");
    }
  } catch (err) {
    // If we can't reach the server, hide login modal
    loginModal.classList.add("hidden");
  }
}

loginBtn.addEventListener("click", async () => {
  const password = loginPassword.value;
  if (!password) {
    loginHint.textContent = "请输入密码。";
    return;
  }
  try {
    loginHint.textContent = "验证中…";
    const resp = await api("/admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    adminToken = resp.admin_token || "";
    if (adminToken) {
      localStorage.setItem("avalon_admin_token", adminToken);
      loginModal.classList.add("hidden");
      adminStatusEl.textContent = "已登录";
      loginHint.textContent = "";
      loginPassword.value = "";
    } else {
      loginHint.textContent = "登录失败。";
    }
  } catch (err) {
    loginHint.textContent = err.message;
  }
});

// Allow Enter key to submit login
loginPassword.addEventListener("keydown", (e) => {
  if (e.key === "Enter") loginBtn.click();
});

function updateRoleHint() {
  const active = [...roleGrid.querySelectorAll(".role-toggle.active[data-role]")].map(
    (btn) => btn.dataset.role
  );
  const lady = ladyToggle.classList.contains("active") ? "湖中夫人已启用" : "湖中夫人未启用";
  roleHintEl.textContent = `必选：${mandatoryRoles.join("、")}。已选：${active.join("、") || "无"}。${lady}。`;
}

updateRoleHint();
updateTotals();
updateVisibility();
checkAdminStatus();
refreshState();
refreshEvents();
setInterval(refreshState, 2000);
setInterval(refreshEvents, 4000);
