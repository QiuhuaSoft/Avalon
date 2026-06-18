// Behavioral XSS-regression test for avalon/web/game.js.
//
// Player names are attacker-controlled (any remote player picks their own name
// in the lobby) and are echoed into the host's game view. The host's browser
// holds localhost privileges (host token, game/tunnel control), so a name that
// reaches innerHTML as live markup is a stored-XSS -> privilege-escalation bug.
//
// This loads game.js in a sandboxed VM behind a tiny DOM shim, renders a
// malicious name through the two functions that build player nodes, and asserts
// the payload only ever appears as inert text -- never inside an innerHTML
// assignment. Run via `node --test`; the pytest gate skips when node is absent.

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
// AVALON_GAME_JS lets the pre-fix (vulnerable) build be pointed at for a
// negative check; defaults to the real frontend source.
const GAME_JS = process.env.AVALON_GAME_JS || join(HERE, "..", "..", "avalon", "web", "game.js");
const PAYLOAD = '<img src=x onerror="window.__pwned=1">';

// Every string assigned to any element's innerHTML lands here so the test can
// prove the payload never crossed the HTML-parsing boundary.
const htmlAssignments = [];
const registry = new Map();

class StubElement {
  constructor(tag) {
    this.tagName = String(tag || "div").toUpperCase();
    this._text = "";
    this._html = "";
    this.children = [];
    this.className = "";
    this.dataset = {};
    this.style = {};
    this.value = "";
    this.options = [];
    this.disabled = false;
    this._classes = new Set();
    this.classList = {
      add: (c) => this._classes.add(c),
      remove: (c) => this._classes.delete(c),
      toggle: (c, force) => {
        const want = force === undefined ? !this._classes.has(c) : force;
        if (want) this._classes.add(c);
        else this._classes.delete(c);
        return want;
      },
      contains: (c) => this._classes.has(c),
    };
  }

  set textContent(v) {
    this._text = String(v);
    this.children = [];
  }

  get textContent() {
    if (this.children.length) return this.children.map((c) => c.textContent).join("");
    return this._text;
  }

  set innerHTML(v) {
    this._html = String(v);
    htmlAssignments.push(this._html);
    this.children = [];
    this._text = "";
  }

  get innerHTML() {
    return this._html;
  }

  appendChild(child) {
    child.parent = this;
    this.children.push(child);
    return child;
  }

  addEventListener() {}
  querySelectorAll() {
    return [];
  }
  querySelector() {
    return null;
  }
}

function collectText(el) {
  let out = el._text || "";
  for (const child of el.children) out += collectText(child);
  return out;
}

function makeSandbox() {
  const documentStub = {
    getElementById(id) {
      if (!registry.has(id)) registry.set(id, new StubElement("div"));
      return registry.get(id);
    },
    createElement(tag) {
      return new StubElement(tag);
    },
  };
  const localStorageStub = {
    getItem: (key) => (key === "avalon_player_id" ? "p2" : null),
    setItem: () => {},
    removeItem: () => {},
  };
  const sandbox = {
    document: documentStub,
    window: { location: { search: "", href: "http://localhost/game", hostname: "localhost" } },
    localStorage: localStorageStub,
    // Never resolves: the module's bootstrap refresh() suspends here instead of
    // touching the DOM further during the test.
    fetch: () => new Promise(() => {}),
    setInterval: () => 0,
    clearInterval: () => {},
    URLSearchParams,
    console,
    Promise,
  };
  sandbox.globalThis = sandbox;
  return sandbox;
}

function loadGame() {
  const src = readFileSync(GAME_JS, "utf8");
  const sandbox = makeSandbox();
  vm.createContext(sandbox);
  vm.runInContext(src, sandbox, { filename: "game.js" });
  return sandbox;
}

test("renderPlayerTable renders names as inert text, not markup", () => {
  const game = loadGame();
  htmlAssignments.length = 0;
  game.renderPlayerTable([{ id: "p1", name: PAYLOAD, alignment_hint: "evil" }], "p1");

  for (const html of htmlAssignments) {
    assert.ok(
      !html.includes("<img"),
      `player name leaked into an innerHTML assignment: ${html}`,
    );
  }
  const table = registry.get("playerTable");
  assert.ok(
    collectText(table).includes(PAYLOAD),
    "the name should still render (as text) in the player card",
  );
});

test("renderEndgameReveal reveals roles and renders names as inert text", () => {
  const game = loadGame();
  htmlAssignments.length = 0;
  // Outcome chosen so describeOutcome's sentence does NOT itself name any role
  // (a quest-loss, not an assassination). That way the role assertions below
  // genuinely exercise the per-player reveal grid rather than the summary line.
  const state = {
    winner: "evil",
    assassin_target: null,
    fail_count: 3,
    players: [
      { id: "p1", name: PAYLOAD, role: "Merlin" },
      { id: "p2", name: "Bob", role: "Assassin" },
      { id: "p3", name: "Cara", role: "Loyal Servant" },
    ],
  };
  game.renderEndgameReveal(state);

  for (const html of htmlAssignments) {
    assert.ok(
      !html.includes("<img"),
      `revealed name leaked into an innerHTML assignment: ${html}`,
    );
  }
  const panel = registry.get("actionPanel");
  // Locate the role grid specifically, so the assertions can't be satisfied by
  // the headline/outcome text alone (deleting the grid loop must fail the test).
  const grid = panel.children.find((c) => c.className === "reveal-grid");
  assert.ok(grid, "the reveal should render a per-player role grid");
  const gridText = collectText(grid);
  assert.ok(gridText.includes(PAYLOAD), "the revealed player name should render as text");
  assert.ok(
    gridText.includes("Merlin")
      && gridText.includes("Assassin")
      && gridText.includes("Loyal Servant"),
    "every player's true role should appear in the reveal grid",
  );
});

test("renderActionMenu hint renders leader name as inert text", () => {
  const game = loadGame();
  htmlAssignments.length = 0;
  const state = {
    id: "g1",
    phase: "team_proposal",
    leader_index: 0,
    quest_number: 1,
    proposal_attempts: 0,
    config: { player_count: 5 },
    players: [
      { id: "p1", name: PAYLOAD },
      { id: "p2", name: "Bob" },
    ],
    proposed_team: [],
    team_votes: {},
    quest_votes: {},
  };
  // Viewer is p2; leader is p1, so the menu shows "Waiting for <p1 name>...".
  game.renderActionMenu(state, { role: null });

  for (const html of htmlAssignments) {
    assert.ok(
      !html.includes("<img"),
      `leader name leaked into an innerHTML assignment: ${html}`,
    );
  }
  const panel = registry.get("actionPanel");
  assert.ok(
    collectText(panel).includes(PAYLOAD),
    "the leader name should still render (as text) in the hint",
  );
});
