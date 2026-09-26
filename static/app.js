"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  routes: [],            // [{id, name, options: [{method, pokemon, rate, levels}]}]
  battles: [],           // [{id, name, location, level_cap, group_id, tags}] in game order
  sprites: {},           // species -> sprite url (pokeapi.co)
  attempts: [],          // [{id, number, notes, catch_count}]
  attempt: null,         // currently selected attempt
  catches: new Map(),    // route_id -> {id, route_id, pokemon}
  fights: new Map(),     // battle_id -> {id, battle_id, result, members: [{slot, catch_id}]}
  battleId: null,        // battle shown on the Trainer Battles tab
};

const TEAM_SIZE = 6;
const $ = (sel) => document.querySelector(sel);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

async function api(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? {} : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `${res.status} ${res.statusText}`);
  return data;
}

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value === undefined || value === null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key in node && typeof value !== "string") node[key] = value;
    else node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children);
  return node;
}

let statusTimer;
function setStatus(message, kind = "") {
  const status = $("#status");
  status.textContent = message;
  status.className = kind;
  clearTimeout(statusTimer);
  if (kind === "ok") statusTimer = setTimeout(() => (status.textContent = ""), 1500);
}

async function save(action) {
  setStatus("Saving…");
  try {
    const result = await action();
    setStatus("Saved", "ok");
    return result;
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error");
    throw err;
  }
}

function storageGet(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}
function storageSet(key, value) {
  try { localStorage.setItem(key, value); } catch { /* storage unavailable */ }
}

// ---------------------------------------------------------------------------
// Attempts
// ---------------------------------------------------------------------------

async function loadAttempts(preferredId) {
  state.attempts = (await api("GET", "/attempts")).attempts;
  const select = $("#attempt-select");
  select.replaceChildren(
    ...state.attempts.map((a) =>
      el("option", { value: a.id }, `#${a.number} (${a.catch_count} caught)`))
  );
  const hasAttempts = state.attempts.length > 0;
  $("#main").hidden = !hasAttempts;
  $("#no-attempts").hidden = hasAttempts;
  $("#delete-attempt").disabled = !hasAttempts;
  if (!hasAttempts) {
    state.attempt = null;
    return;
  }
  const wanted = [preferredId, Number(storageGet("attemptId"))]
    .find((id) => state.attempts.some((a) => a.id === id));
  await selectAttempt(wanted ?? state.attempts[0].id);
}

async function selectAttempt(id) {
  const data = await api("GET", `/attempts/${id}`);
  state.attempt = data.attempt;
  state.catches = new Map(data.catches.map((c) => [c.route_id, c]));
  state.fights = new Map(data.fights.map((f) => [f.battle_id, f]));
  $("#attempt-select").value = id;
  storageSet("attemptId", id);
  renderEncounters();
  renderFightView();
  $("#notes").value = state.attempt.notes;
}

function refreshAttemptLabel() {
  const summary = state.attempts.find((a) => a.id === state.attempt.id);
  summary.catch_count = state.catches.size;
  const option = $(`#attempt-select option[value="${state.attempt.id}"]`);
  option.textContent = `#${summary.number} (${summary.catch_count} caught)`;
  $("#catch-count").textContent = `${state.catches.size}/${state.routes.length}`;
}

async function createAttempt() {
  const next = Math.max(0, ...state.attempts.map((a) => a.number)) + 1;
  const input = prompt("Attempt number:", next);
  if (input === null) return;
  const number = Number.parseInt(input, 10);
  if (!Number.isInteger(number)) return setStatus("Error: attempt number must be a whole number", "error");
  const { attempt } = await save(() => api("POST", "/attempts", { number }));
  await loadAttempts(attempt.id);
}

async function deleteAttempt() {
  const a = state.attempt;
  if (!a || !confirm(`Delete attempt #${a.number} and all its catches and fights?`)) return;
  await save(() => api("DELETE", `/attempts/${a.id}`));
  await loadAttempts();
}

// ---------------------------------------------------------------------------
// Encounters tab
// ---------------------------------------------------------------------------

let pickerRoute = null;  // route whose catch picker is open

function renderEncounters() {
  const rows = state.routes.map((route) =>
    el("tr", { "data-route": route.id }, el("td", {}, route.name), el("td", {}, catchCell(route))));
  $("#encounters-body").replaceChildren(...rows);
  refreshAttemptLabel();
}

/** "+ Add catch", or the catch itself (click to change) with a remove button. */
function catchCell(route) {
  const current = state.catches.get(route.id);
  if (!current) {
    const add = el("button", { type: "button", class: "add-catch" }, "+ Add catch");
    add.addEventListener("click", () => openCatchPicker(route));
    return add;
  }
  const change = el("button", { type: "button", class: "catch-chip", title: `Change what you caught on ${route.name}` },
    sprite(current.pokemon), el("span", { class: "mon-name" }, current.pokemon));
  change.addEventListener("click", () => openCatchPicker(route));
  const remove = el("button", { type: "button", class: "catch-remove", "aria-label": `Remove ${current.pokemon} from ${route.name}` }, "×");
  remove.addEventListener("click", () => removeCatch(route));
  return el("div", { class: "catch-cell" }, change, remove);
}

function refreshCatchCell(route) {
  $(`#encounters-body tr[data-route="${route.id}"] td:last-child`)?.replaceChildren(catchCell(route));
}

// --- catch picker (popup) ----------------------------------------------------------

function openCatchPicker(route) {
  pickerRoute = route;
  const current = state.catches.get(route.id)?.pokemon;
  $("#picker-title").textContent = route.name;
  $("#picker-sub").textContent = current ? `Caught: ${current}. Pick another to change it.` : "What did you catch here?";

  // One grid per encounter method (Land, Fishing, Surf, ...), in the sheet's order.
  const methods = new Map();
  for (const opt of route.options) {
    if (!methods.has(opt.method)) methods.set(opt.method, []);
    methods.get(opt.method).push(opt);
  }
  $("#picker-body").replaceChildren(...[...methods].map(([method, options]) =>
    el("section", { class: "picker-section" },
      el("h3", {}, method),
      el("div", { class: "picker-grid" }, ...options.map((opt) => pickerCard(route, opt, current))))));
  $("#picker-remove").hidden = !current;
  $("#catch-picker").showModal();
}

function pickerCard(route, opt, current) {
  // Gift and fossil slots have descriptive "levels" ("Fossil", "Badge 2") instead of numbers.
  const levels = opt.levels ? opt.levels.split(",").join(", ") : "";
  const detail = /[a-z]/i.test(levels) ? levels : levels && `Lv ${levels}`;
  const card = el("button", {
    type: "button",
    class: "pick-card",
    "aria-pressed": String(opt.pokemon === current),
  },
    sprite(opt.pokemon),
    el("span", { class: "mon-name" }, opt.pokemon),
    el("span", { class: "pick-odds" }, opt.rate ? `${opt.rate}%` : "—"),
    el("span", { class: "mon-route" }, detail));
  card.addEventListener("click", () => {
    $("#catch-picker").close();
    if (opt.pokemon !== current) saveCatch(route, opt.pokemon);
  });
  return card;
}

async function removeCatch(route) {
  const current = state.catches.get(route.id);
  if (!current) return;
  // Clearing a catch also takes it off every team it was on (the server cascades).
  const teams = [...state.fights.values()].filter((f) => f.members.some((m) => m.catch_id === current.id)).length;
  if (teams && !confirm(`${current.pokemon} is on ${teams} team${teams > 1 ? "s" : ""}. Removing it also takes it off ${teams > 1 ? "those teams" : "that team"}. Continue?`)) {
    return;
  }
  await saveCatch(route, null);
}

async function saveCatch(route, pokemon) {
  const attemptId = state.attempt.id;
  try {
    const { catch: saved } = await save(() =>
      api("PUT", `/attempts/${attemptId}/catches/${route.id}`, { pokemon }));
    if (state.attempt?.id !== attemptId) return;  // user switched attempts mid-save
    if (saved) {
      state.catches.set(route.id, saved);
    } else {
      state.catches.delete(route.id);
      const data = await api("GET", `/attempts/${attemptId}`);
      state.fights = new Map(data.fights.map((f) => [f.battle_id, f]));
    }
    refreshCatchCell(route);
    refreshAttemptLabel();
    renderFightView();
  } catch { /* save() already reported the error; the cell still shows the saved state */ }
}

// ---------------------------------------------------------------------------
// Trainer Battles tab: battle list drawer + focus view (enemy team, your team, box)
// ---------------------------------------------------------------------------

const mobileLayout = window.matchMedia("(max-width: 760px)");
const HIDDEN_TAGS = new Set(["Boss", "Tag Partner"]);  // conveyed by the layout instead
let dragging = null;                 // {catchId, fromSlot} while a drag is in progress
let saveChain = Promise.resolve();   // fight saves run one at a time, in order
const fightEdits = new Map();        // battle_id -> edit counter, to ignore stale responses
const battleDetails = new Map();     // battle_id -> {battle, trainers} (loaded on demand)
const openGroups = new Set();        // level-cap battle ids whose trainer list is expanded
const trainerChoice = new Map();     // battle_id -> index of the trainer shown
let renderedEnemy = null;            // "battleId:trainerIndex" currently drawn

/** Caught Pokemon for this attempt, in route order. */
function box() {
  return state.routes
    .filter((r) => state.catches.has(r.id))
    .map((r) => ({ ...state.catches.get(r.id), routeName: r.name }));
}

/** A fight's team as six slots of catch ids (null = empty). */
function teamSlots(fight) {
  const slots = Array(TEAM_SIZE).fill(null);
  for (const m of fight?.members ?? []) slots[m.slot - 1] = m.catch_id;
  return slots;
}

const currentBattle = () => state.battles.find((b) => b.id === state.battleId);
const currentSlots = () => teamSlots(state.fights.get(state.battleId));
const levelCapBattles = () => state.battles.filter((b) => b.level_cap !== null);

function sprite(species) {
  const fallback = () => el("span", { class: "sprite sprite-missing", "aria-hidden": "true" }, species.slice(0, 2));
  const url = state.sprites[species];
  if (!url) return fallback();
  const img = el("img", { class: "sprite", src: url, alt: "", draggable: "false" });
  img.addEventListener("error", () => img.replaceWith(fallback()), { once: true });
  return img;
}

function monLabel(mon) {
  return [sprite(mon.pokemon),
    el("span", { class: "mon-name" }, mon.pokemon),
    el("span", { class: "mon-route" }, mon.routeName)];
}

function defaultBattleId() {
  const stored = Number(storageGet("battleId"));
  if (state.battles.some((b) => b.id === stored)) return stored;
  // Otherwise the first level-cap fight with nothing recorded yet.
  const bosses = levelCapBattles();
  return (bosses.find((b) => !state.fights.has(b.id)) ?? bosses[0]).id;
}

function renderFightView() {
  if (!state.attempt || !state.battles.length) return;
  const first = state.battleId === null;
  if (first) {
    state.battleId = defaultBattleId();
    revealInList(currentBattle());
  }
  renderBattleList();
  if (first) $("#battle-list [aria-current]")?.scrollIntoView({ block: "nearest" });
  renderFocus();
  renderEnemy();
}

// --- battle list (drawer) ------------------------------------------------------

/**
 * One dropdown per split: the trainers leading up to a level-cap battle, in
 * game order, ending with the level-cap battle itself.
 */
function renderBattleList() {
  const query = $("#battle-filter").value.trim().toLowerCase();
  const matches = (b) => !query || `${b.name} ${b.location ?? ""}`.toLowerCase().includes(query);
  const groups = levelCapBattles().map((boss) => {
    const battles = [...state.battles.filter((b) => b.group_id === boss.id), boss];
    const shown = battles.filter(matches);
    if (!shown.length) return null;
    const open = Boolean(query) || openGroups.has(boss.id);
    const result = state.fights.get(boss.id)?.result;
    const toggle = el("button", {
      type: "button",
      class: `group-toggle ${result ?? ""}`,
      "aria-expanded": String(open),
    },
      el("span", { class: "chevron", "aria-hidden": "true" }, "▸"),
      el("span", { class: "group-name" }, `${boss.name} Split`),
      el("span", { class: "battle-status", title: `${boss.name}: ${result ?? "not fought"}` },
        { won: "✓", lost: "✗" }[result] ?? ""),
      el("span", { class: "group-meta" }, `Level cap ${boss.level_cap} · ${battles.length} battles`));
    toggle.addEventListener("click", () => {
      if (openGroups.has(boss.id)) openGroups.delete(boss.id);
      else openGroups.add(boss.id);
      renderBattleList();
    });
    return el("li", { class: "battle-group" },
      toggle,
      el("ol", { class: "trainer-list", hidden: !open },
        ...shown.map((b) => el("li", {}, battleButton(b, b === boss ? "boss-item" : "trainer-item")))));
  }).filter(Boolean);
  $("#battle-list").replaceChildren(...groups);
  $("#no-matches").hidden = groups.length > 0;
}

function battleButton(battle, className) {
  const fight = state.fights.get(battle.id);
  const count = fight?.members.length ?? 0;
  const meta = [battle.location, count && `${count}/${TEAM_SIZE}`].filter(Boolean);
  const tags = battle.tags.filter((t) => !HIDDEN_TAGS.has(t));
  if (battle.level_cap !== null) tags.unshift("Boss");
  const button = el("button", {
    type: "button",
    class: `${className} ${fight?.result ?? ""}`,
    "aria-current": battle.id === state.battleId ? "true" : undefined,
  },
    el("span", { class: "battle-status", title: fight?.result ?? "not fought" },
      { won: "✓", lost: "✗" }[fight?.result] ?? ""),
    el("span", { class: "battle-name" }, battle.name,
      ...tags.map((t) => el("span", { class: t === "Boss" ? "tag boss" : "tag" }, t))),
    el("span", { class: "battle-meta" }, meta.join(" · ")));
  button.addEventListener("click", () => selectBattle(battle.id));
  return button;
}

/** Expand the split holding a battle so it's visible in the list. */
function revealInList(battle) {
  if (battle) openGroups.add(battle.group_id ?? battle.id);
}

// --- focus: header, your team, box ---------------------------------------------

function renderFocus() {
  const battle = currentBattle();
  const fight = state.fights.get(battle.id);
  const slots = teamSlots(fight);
  const mons = box();
  const byId = new Map(mons.map((m) => [m.id, m]));

  // The split's level cap sits above the name, for regular trainers too.
  const split = battle.level_cap !== null ? battle : state.battles.find((b) => b.id === battle.group_id);
  $("#focus-cap").hidden = !split;
  $("#focus-cap").replaceChildren(...(split ? [
    el("strong", { class: "cap-badge" }, `Level cap ${split.level_cap}`),
    el("span", { class: "muted" }, `${split.name} Split`),
  ] : []));
  $("#focus-name").textContent = battle.name;
  $("#focus-sub").textContent = [battle.location, ...battle.tags.filter((t) => !HIDDEN_TAGS.has(t))]
    .filter(Boolean).join(" · ");
  for (const btn of document.querySelectorAll(".result-toggle button")) {
    btn.setAttribute("aria-pressed", fight?.result === btn.dataset.result);
  }

  $("#team-count").textContent = `${slots.filter(Boolean).length}/${TEAM_SIZE}`;
  $("#team-grid").replaceChildren(...slots.map((catchId, i) => teamSlot(i, byId.get(catchId))));

  $("#box-count").textContent = `(${mons.length} caught)`;
  $("#empty-box").hidden = mons.length > 0;
  $("#box-grid").replaceChildren(...mons.map((m) => boxMon(m, slots.indexOf(m.id))));
}

// --- focus: enemy team -----------------------------------------------------------

async function loadBattle(battleId) {
  if (!battleDetails.has(battleId)) {
    battleDetails.set(battleId, await api("GET", `/battles/${battleId}`));
  }
  return battleDetails.get(battleId);
}

/** Short trainer names for the switcher: "Trainer Rival Cycling Road Sceptile" -> "Sceptile". */
function trainerLabels(trainers) {
  const enemies = trainers.filter((t) => !t.tags.includes("Tag Partner")).map((t) => t.name.split(" "));
  let common = 0;
  while (enemies.length > 1 && enemies.every((w) => w.length > common + 1 && w[common] === enemies[0][common])) {
    common++;
  }
  return trainers.map((t) => {
    if (t.tags.includes("Tag Partner")) return `${t.name} (ally)`;
    const words = t.name.split(" ");
    // Keep one word of context for bare numbers: "Museum #1" rather than "#1".
    const start = /^#?\d+$/.test(words[common] ?? "") ? Math.max(common - 1, 0) : common;
    return words.slice(start).join(" ");
  });
}

function renderEnemy() {
  const battleId = state.battleId;
  const detail = battleDetails.get(battleId);
  const index = Math.min(trainerChoice.get(battleId) ?? 0, (detail?.trainers.length ?? 1) - 1);
  const key = `${battleId}:${index}`;
  if (key === renderedEnemy) return;  // unchanged; avoid redrawing sprites on every team edit

  if (!detail) {
    renderedEnemy = null;
    $("#trainer-tabs").replaceChildren();
    $("#enemy-note").hidden = true;
    $("#enemy-slots").replaceChildren(...Array.from({ length: TEAM_SIZE }, () => enemySlot(null, "…")));
    loadBattle(battleId)
      .then(() => { if (state.battleId === battleId) renderEnemy(); })
      .catch((err) => setStatus(`Error: ${err.message}`, "error"));
    return;
  }
  renderedEnemy = key;

  const trainers = detail.trainers;
  const labels = trainerLabels(trainers);
  $("#trainer-tabs").replaceChildren(...(trainers.length > 1 ? trainers.map((t, i) => {
    const tab = el("button", { type: "button", "aria-pressed": String(i === index), title: t.name }, labels[i]);
    tab.addEventListener("click", () => {
      trainerChoice.set(battleId, i);
      renderEnemy();
    });
    return tab;
  }) : []));

  const trainer = trainers[index];
  const ally = trainer.tags.includes("Tag Partner");
  $("#enemy-heading").textContent = ally ? "Partner's team" : "Enemy team";
  $("#enemy-note").hidden = !ally;
  $("#enemy-note").textContent = ally ? `${trainer.name} fights on your side in this tag battle.` : "";
  $("#enemy-slots").replaceChildren(...Array.from({ length: TEAM_SIZE }, (_, i) => enemySlot(trainer.pokemon[i])));
}

/**
 * One enemy Pokemon as a card: sprite, name and level, then its item /
 * ability / nature in one block and its moves as a 2x2 grid in another.
 */
function enemySlot(mon, placeholder = "") {
  if (!mon) {
    return el("div", { class: "enemy-col" }, el("div", { class: "enemy-slot" }, placeholder));
  }
  const stats = [["Item", mon.item], ["Ability", mon.ability], ["Nature", mon.nature]]
    .flatMap(([label, value]) => [el("dt", {}, label), el("dd", {}, value ?? "—")]);
  // Always four cells, so the grid keeps its 2x2 shape when a Pokemon knows fewer moves.
  const moves = [...mon.moves, null, null, null, null].slice(0, 4);
  return el("div", { class: "enemy-col filled" },
    el("div", { class: "enemy-slot filled" },
      sprite(mon.species),
      el("span", { class: "mon-name" }, mon.species),
      el("span", { class: "mon-route" }, mon.level ? `Lv ${mon.level}` : "")),
    el("dl", { class: "enemy-block enemy-stats" }, ...stats),
    el("ul", { class: "enemy-block enemy-moves", "aria-label": `${mon.species}'s moves` },
      ...moves.map((move) => el("li", { class: move ? "move" : "move empty" }, move ?? "—"))));
}

// --- focus: your team + box ------------------------------------------------------

function teamSlot(index, mon) {
  const slot = el("div", { class: `team-slot${mon ? " filled" : ""}` });
  if (mon) {
    const remove = el("button", { type: "button", class: "remove", "aria-label": `Remove ${mon.pokemon} from the team` }, "×");
    remove.addEventListener("click", () => setSlot(index, null));
    slot.append(...monLabel(mon), remove);
    slot.title = `${mon.pokemon} (${mon.routeName}): drag to another slot to swap, or back to the box to remove`;
    makeDraggable(slot, { catchId: mon.id, fromSlot: index });
  } else {
    slot.append(el("span", { class: "slot-empty" }, `Slot ${index + 1}`));
  }
  makeDropTarget(slot, (drag) => moveTo(drag.catchId, index));
  return slot;
}

function boxMon(mon, teamIndex) {
  const onTeam = teamIndex !== -1;
  const node = el("div", {
    class: `box-mon${onTeam ? " on-team" : ""}`,
    role: "button",
    tabindex: "0",
    "aria-pressed": String(onTeam),
    title: `${mon.pokemon} (${mon.routeName})${onTeam ? ": on the team" : ""}`,
  }, ...monLabel(mon));
  const toggle = () => {
    if (onTeam) return setSlot(teamIndex, null);
    const empty = currentSlots().indexOf(null);
    if (empty === -1) return setStatus("Team is full: drag onto a slot to replace someone", "error");
    setSlot(empty, mon.id);
  };
  node.addEventListener("click", toggle);
  node.addEventListener("keydown", (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); }
  });
  makeDraggable(node, { catchId: mon.id, fromSlot: onTeam ? teamIndex : null });
  return node;
}

// --- drag and drop ---------------------------------------------------------

function makeDraggable(node, payload) {
  node.setAttribute("draggable", "true");
  node.addEventListener("dragstart", (e) => {
    dragging = payload;
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(payload.catchId));  // Firefox needs data set
    const img = node.querySelector("img");
    if (img) e.dataTransfer.setDragImage(img, img.width / 2, img.height / 2);
    node.classList.add("dragging");
  });
  node.addEventListener("dragend", () => {
    dragging = null;
    node.classList.remove("dragging");
  });
}

function makeDropTarget(node, onDrop, accepts = () => true) {
  node.addEventListener("dragover", (e) => {
    if (!dragging || !accepts(dragging)) return;
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    node.classList.add("drag-over");
  });
  node.addEventListener("dragleave", (e) => {
    if (!node.contains(e.relatedTarget)) node.classList.remove("drag-over");
  });
  node.addEventListener("drop", (e) => {
    e.preventDefault();
    node.classList.remove("drag-over");
    const drag = dragging;
    dragging = null;
    if (drag && accepts(drag)) onDrop(drag);
  });
}

// --- team edits --------------------------------------------------------------

/** Put a catch into a slot. If it was already on the team, swap the two slots. */
function moveTo(catchId, index) {
  const slots = currentSlots();
  const from = slots.indexOf(catchId);
  if (from === index) return;
  const displaced = slots[index];
  slots[index] = catchId;
  if (from !== -1) slots[from] = displaced;
  saveFight(slots, state.fights.get(state.battleId)?.result ?? null);
}

function setSlot(index, catchId) {
  const slots = currentSlots();
  slots[index] = catchId;
  saveFight(slots, state.fights.get(state.battleId)?.result ?? null);
}

function toggleResult(result) {
  const current = state.fights.get(state.battleId)?.result ?? null;
  saveFight(currentSlots(), current === result ? null : result);
}

/** Apply a fight change immediately, then save it in the background. */
function saveFight(slots, result) {
  const attemptId = state.attempt.id;
  const battleId = state.battleId;
  const members = slots.flatMap((catchId, i) => (catchId ? [{ slot: i + 1, catch_id: catchId }] : []));
  if (members.length || result) {
    state.fights.set(battleId, { ...state.fights.get(battleId), battle_id: battleId, result, members });
  } else {
    state.fights.delete(battleId);
  }
  renderFightView();

  const edit = (fightEdits.get(battleId) ?? 0) + 1;
  fightEdits.set(battleId, edit);
  saveChain = saveChain.then(async () => {
    try {
      const { fight } = await save(() =>
        api("PUT", `/attempts/${attemptId}/fights/${battleId}`, { members: slots, result }));
      // Keep the optimistic state if the user switched attempts or edited again since.
      if (state.attempt?.id !== attemptId || fightEdits.get(battleId) !== edit) return;
      if (fight) state.fights.set(battleId, fight);
      else state.fights.delete(battleId);
    } catch {
      // Save failed: resync with what the server actually has.
      if (state.attempt?.id !== attemptId) return;
      const data = await api("GET", `/attempts/${attemptId}`).catch(() => null);
      if (!data || state.attempt?.id !== attemptId) return;
      state.catches = new Map(data.catches.map((c) => [c.route_id, c]));
      state.fights = new Map(data.fights.map((f) => [f.battle_id, f]));
      renderEncounters();
      renderFightView();
    }
  });
}

// --- battle list drawer ---------------------------------------------------------

function selectBattle(id) {
  state.battleId = id;
  storageSet("battleId", id);
  revealInList(currentBattle());
  if (mobileLayout.matches) setDrawer(false);
  renderFightView();
}

function setDrawer(open) {
  $("#tab-fights").classList.toggle("drawer-closed", !open);
  $("#drawer-open").setAttribute("aria-expanded", String(open));
}

// ---------------------------------------------------------------------------
// Notes tab
// ---------------------------------------------------------------------------

async function onNotesChange() {
  const notes = $("#notes").value;
  const current = state.attempt;
  if (!current || notes === current.notes) return;
  const { attempt } = await save(() => api("PATCH", `/attempts/${current.id}`, { notes }));
  if (state.attempt?.id === attempt.id) state.attempt = attempt;
}

// ---------------------------------------------------------------------------
// Tabs + boot
// ---------------------------------------------------------------------------

function showTab(name) {
  for (const btn of document.querySelectorAll(".tabs button")) {
    const active = btn.dataset.tab === name;
    btn.setAttribute("aria-selected", active);
    $(`#tab-${btn.dataset.tab}`).hidden = !active;
  }
  // Opening Trainer Battles slides the battle list out (a CSS animation that replays
  // whenever the tab goes from hidden to shown).
  if (name === "fights") {
    setDrawer(true);
    $("#battle-list [aria-current]")?.scrollIntoView({ block: "nearest" });
  }
  storageSet("tab", name);
}

async function boot() {
  try {
    const game = await api("GET", "/game");
    state.routes = game.routes;
    state.battles = game.battles;
    state.sprites = game.sprites;

    for (const btn of document.querySelectorAll(".tabs button")) {
      btn.addEventListener("click", () => showTab(btn.dataset.tab));
    }
    showTab(["encounters", "fights", "notes"].includes(storageGet("tab")) ? storageGet("tab") : "encounters");

    $("#drawer-open").addEventListener("click", () =>
      setDrawer($("#tab-fights").classList.contains("drawer-closed")));
    $("#drawer-close").addEventListener("click", () => setDrawer(false));
    $("#drawer-scrim").addEventListener("click", () => setDrawer(false));
    $("#battle-filter").addEventListener("input", renderBattleList);
    $("#picker-remove").addEventListener("click", () => {
      $("#catch-picker").close();
      removeCatch(pickerRoute).catch(() => {});
    });
    // Clicking the dimmed backdrop (outside .picker-inner) closes the picker.
    $("#catch-picker").addEventListener("click", (e) => {
      if (e.target === e.currentTarget) e.currentTarget.close();
    });
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && mobileLayout.matches) setDrawer(false);
    });
    for (const btn of document.querySelectorAll(".result-toggle button")) {
      btn.addEventListener("click", () => toggleResult(btn.dataset.result));
    }
    // Dropping a team member back on the box removes it from the team.
    makeDropTarget($("#box-panel"), (drag) => setSlot(drag.fromSlot, null),
      (drag) => drag.fromSlot !== null);

    $("#attempt-select").addEventListener("change", (e) => selectAttempt(Number(e.target.value)));
    $("#new-attempt").addEventListener("click", () => createAttempt().catch(() => {}));
    $("#delete-attempt").addEventListener("click", () => deleteAttempt().catch(() => {}));
    $("#notes").addEventListener("change", () => onNotesChange().catch(() => {}));

    await loadAttempts();
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error");
  }
}

boot();
