// Logic tests for the proposal-history reconstruction in avalon/web/game.js.
//
// `buildProposalRecords` folds the *redacted* public event stream
// (`public_events()` in avalon/api.py withholds each round's team_vote events
// until the proposal resolves, and drops quest_vote events entirely) back into
// the per-proposal rows the game view's matrix renders. `missionSummary` turns
// one row into its mission verdict, and `hammerText` describes how close the
// round is to the hammer / the five-rejection loss. All three are pure
// functions, so this loads game.js behind a tiny shim (just enough for the
// module to evaluate) and exercises them directly. Run via `node --test`; the
// pytest gate in tests/test_web_logic.py skips when node is absent.

import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const HERE = dirname(fileURLToPath(import.meta.url));
const GAME_JS = join(HERE, "..", "..", "avalon", "web", "game.js");

// game.js renders into the DOM and kicks off a poll loop on load. None of that
// is needed here (the functions under test are pure), so the shim only has to
// let the module evaluate: hand back inert elements, and make fetch hang so the
// bootstrap refresh() suspends instead of touching anything further.
class StubElement {
  constructor() {
    this._text = "";
    this.value = "";
    this.classList = { add() {}, remove() {}, toggle() { return false; }, contains() { return false; } };
  }
  set textContent(v) { this._text = String(v); }
  get textContent() { return this._text; }
  set innerHTML(_v) {}
  get innerHTML() { return ""; }
  appendChild(child) { return child; }
  addEventListener() {}
}

function loadGame() {
  const sandbox = {
    document: {
      getElementById: () => new StubElement(),
      createElement: () => new StubElement(),
    },
    window: { location: { search: "", href: "http://localhost/game", hostname: "localhost" } },
    localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    fetch: () => new Promise(() => {}),
    setInterval: () => 0,
    clearInterval: () => {},
    URLSearchParams,
    console,
    Promise,
  };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(readFileSync(GAME_JS, "utf8"), sandbox, { filename: "game.js" });
  return sandbox;
}

// Objects returned from the VM carry the sandbox realm's prototypes, which
// trips deepStrictEqual's prototype check. Round-trip through JSON to compare
// them as plain test-realm values (every field here is JSON-safe).
const plain = (v) => JSON.parse(JSON.stringify(v));

// --- event-stream builders (mirroring public_events() ordering) -------------
const ev = (type, payload = {}) => ({ type, payload });
const created = () => ev("game_created", { player_count: 5 });
const started = () => ev("game_started", {});
const proposed = (leader, team) => ev("team_proposed", { leader_id: leader, team });
const vote = (pid, approve) => ev("team_vote", { player_id: pid, approve });
const approved = (approvals, rejects) => ev("team_approved", { approvals, rejects });
const rejected = (approvals, rejects) => ev("team_rejected", { approvals, rejects });
const hammered = (team) => ev("team_hammered", { team });
const resolved = (quest, fails, succeeded) => ev("quest_resolved", { quest, fails, succeeded });

// The five ballots of a round, in the order public_events() reveals them
// (all together, just before the resolution event).
const ballots = (votes) => Object.entries(votes).map(([pid, ok]) => vote(pid, ok));

test("buildProposalRecords folds an approved proposal and its mission", () => {
  const game = loadGame();
  const records = plain(game.buildProposalRecords([
    created(), started(),
    proposed("p1", ["p1", "p2"]),
    ...ballots({ p1: true, p2: true, p3: true, p4: false, p5: false }),
    approved(3, 2),
    resolved(1, 0, true),
  ]));

  assert.equal(records.length, 1);
  const r = records[0];
  assert.equal(r.quest, 1);
  assert.equal(r.attempt, 1);
  assert.equal(r.leaderId, "p1");
  assert.deepEqual(r.team, ["p1", "p2"]);
  assert.equal(r.result, "approved");
  assert.equal(r.approvals, 3);
  assert.equal(r.rejects, 2);
  // The withheld ballots are all attributed to this proposal once revealed.
  assert.deepEqual(r.votes, { p1: true, p2: true, p3: true, p4: false, p5: false });
  assert.equal(r.missionResolved, true);
  assert.equal(r.missionSucceeded, true);
  assert.equal(r.missionFails, 0);
});

test("buildProposalRecords increments the attempt across a re-proposal", () => {
  const game = loadGame();
  const records = plain(game.buildProposalRecords([
    created(), started(),
    proposed("p1", ["p1", "p2"]),
    ...ballots({ p1: true, p2: true, p3: false, p4: false, p5: false }),
    rejected(2, 3),
    proposed("p2", ["p2", "p3"]),
    ...ballots({ p1: true, p2: true, p3: true, p4: true, p5: false }),
    approved(4, 1),
    resolved(1, 0, true),
  ]));

  assert.equal(records.length, 2);
  // Same quest, second attempt; the rejected row runs no mission.
  assert.deepEqual(
    records.map((r) => [r.quest, r.attempt, r.result, r.missionResolved]),
    [[1, 1, "rejected", false], [1, 2, "approved", true]],
  );
  assert.equal(records[0].approvals, 2);
  assert.equal(records[0].rejects, 3);
});

test("buildProposalRecords marks a hammered proposal with no ballots", () => {
  const game = loadGame();
  const records = plain(game.buildProposalRecords([
    created(), started(),
    proposed("p1", ["p1", "p2"]),
    hammered(["p1", "p2"]),
    resolved(1, 1, false),
  ]));

  assert.equal(records.length, 1);
  const r = records[0];
  assert.equal(r.hammered, true);
  assert.equal(r.result, "approved");
  assert.equal(r.approvals, null);
  assert.equal(r.rejects, null);
  assert.deepEqual(r.votes, {});
  assert.equal(r.missionResolved, true);
  assert.equal(r.missionSucceeded, false);
  assert.equal(r.missionFails, 1);
});

test("buildProposalRecords advances the quest number across missions", () => {
  const game = loadGame();
  const records = plain(game.buildProposalRecords([
    created(), started(),
    proposed("p1", ["p1", "p2"]),
    ...ballots({ p1: true, p2: true, p3: true, p4: true, p5: true }),
    approved(5, 0),
    resolved(1, 0, true),
    proposed("p2", ["p2", "p3", "p4"]),
    ...ballots({ p1: true, p2: true, p3: true, p4: true, p5: true }),
    approved(5, 0),
    resolved(2, 1, false),
  ]));

  assert.equal(records.length, 2);
  assert.deepEqual(records.map((r) => r.quest), [1, 2]);
  assert.equal(records[1].attempt, 1);
  assert.equal(records[1].missionSucceeded, false);
});

test("buildProposalRecords clears prior records when a new game is created", () => {
  const game = loadGame();
  const records = plain(game.buildProposalRecords([
    created(), started(),
    proposed("p1", ["p1", "p2"]),
    ...ballots({ p1: true, p2: true, p3: true, p4: false, p5: false }),
    approved(3, 2),
    resolved(1, 0, true),
    // A fresh game resets the matrix entirely.
    created(), started(),
    proposed("p3", ["p3", "p4"]),
  ]));

  assert.equal(records.length, 1);
  assert.equal(records[0].leaderId, "p3");
  assert.equal(records[0].quest, 1);
  assert.equal(records[0].attempt, 1);
  assert.equal(records[0].result, "pending");
});

test("missionSummary names each mission state", () => {
  const game = loadGame();
  const summary = (record) => plain(game.missionSummary(record));
  assert.deepEqual(summary({ result: "rejected" }), {
    text: "Not run", cls: "mission-muted",
  });
  assert.deepEqual(summary({ result: "pending" }), {
    text: "Pending vote", cls: "mission-pending",
  });
  assert.deepEqual(summary({ result: "approved", missionResolved: false }), {
    text: "In progress", cls: "mission-pending",
  });
  assert.deepEqual(
    summary({
      result: "approved", missionResolved: true, missionSucceeded: true,
      missionFails: 1, team: ["a", "b", "c"],
    }),
    { text: "PASS (2P/1F)", cls: "mission-pass" },
  );
  assert.deepEqual(
    summary({
      result: "approved", missionResolved: true, missionSucceeded: false,
      missionFails: 2, team: ["a", "b", "c", "d"],
    }),
    { text: "FAIL (2P/2F)", cls: "mission-fail" },
  );
});

test("hammerText tracks the hammer countdown when the hammer is on", () => {
  const game = loadGame();
  assert.equal(game.hammerText(null), "—");
  assert.equal(
    game.hammerText({ config: { hammer_auto_approve: true }, proposal_attempts: 0 }),
    "Proposal 1/5 - 0/4 rejections",
  );
  assert.equal(
    game.hammerText({ config: { hammer_auto_approve: true }, proposal_attempts: 3 }),
    "Proposal 4/5 - 3/4 rejections",
  );
  assert.equal(
    game.hammerText({ config: { hammer_auto_approve: true }, proposal_attempts: 4 }),
    "Proposal 5/5 (HAMMER) - auto-approve",
  );
});

test("hammerText surfaces the five-rejection stakes when the hammer is off", () => {
  const game = loadGame();
  // Without the hammer the tracker must stay informative (it used to read a
  // bare "Disabled"), since this is the only mode where a rejection can lose.
  assert.equal(
    game.hammerText({ config: { hammer_auto_approve: false }, proposal_attempts: 0 }),
    "Proposal 1/5 - 0/4 rejections (no hammer)",
  );
  assert.equal(
    game.hammerText({ config: { hammer_auto_approve: false }, proposal_attempts: 2 }),
    "Proposal 3/5 - 2/4 rejections (no hammer)",
  );
  assert.equal(
    game.hammerText({ config: { hammer_auto_approve: false }, proposal_attempts: 4 }),
    "Proposal 5/5 - reject = Evil wins",
  );
});
