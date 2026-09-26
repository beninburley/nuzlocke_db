"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  routes: [],            // [{id, name, options: [{method, pokemon, rate, levels}]}]
  bosses: [],            // [{id, name, level_cap}]
  attempts: [],          // [{id, number, notes, catch_count}]
  attempt: null,         // currently selected attempt
  catches: new Map(),    // route_id -> {id, route_id, pokemon}
  fights: new Map(),     // boss_id  -> {id, boss_id, result, members: [{slot, catch_id}]}
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

const routeName = (routeId) => state.routes.find((r) => r.id === routeId)?.name ?? "?";

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
  state.fights = new Map(data.fights.map((f) => [f.boss_id, f]));
  $("#attempt-select").value = id;
  storageSet("attemptId", id);
  renderEncounters();
  renderFights();
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

function optionLabel(opt) {
  let label = opt.pokemon;
  // Gift/fossil slots use descriptive "levels" like "Fossil" or "Badge 2".
  if (opt.levels && /[a-z]/i.test(opt.levels)) label += ` [${opt.levels}]`;
  if (opt.rate) label += ` (${opt.rate}%)`;
  return label;
}

function buildRouteSelect(route) {
  const select = el("select", { "aria-label": `Caught on ${route.name}` },
    el("option", { value: "" }, "— none —"));
  const groups = new Map();
  for (const opt of route.options) {
    if (!groups.has(opt.method)) groups.set(opt.method, el("optgroup", { label: opt.method }));
    groups.get(opt.method).append(el("option", { value: opt.pokemon }, optionLabel(opt)));
  }
  select.append(...groups.values());
  return select;
}

function renderEncounters() {
  const rows = state.routes.map((route) => {
    const select = buildRouteSelect(route);
    const current = state.catches.get(route.id);
    select.value = current?.pokemon ?? "";
    select.classList.toggle("filled", Boolean(current));
    select.addEventListener("change", () => onCatchChange(route, select));
    return el("tr", {}, el("td", {}, route.name), el("td", {}, select));
  });
  $("#encounters-body").replaceChildren(...rows);
  refreshAttemptLabel();
}

async function onCatchChange(route, select) {
  const attemptId = state.attempt.id;
  const previous = state.catches.get(route.id)?.pokemon ?? "";
  try {
    const { catch: saved } = await save(() =>
      api("PUT", `/attempts/${attemptId}/catches/${route.id}`, { pokemon: select.value || null }));
    if (state.attempt?.id !== attemptId) return;  // user switched attempts mid-save
    if (saved) {
      state.catches.set(route.id, saved);
    } else {
      // Clearing a catch also removes it from any fight team (server cascades).
      state.catches.delete(route.id);
      const data = await api("GET", `/attempts/${attemptId}`);
      state.fights = new Map(data.fights.map((f) => [f.boss_id, f]));
    }
    select.classList.toggle("filled", Boolean(saved));
    refreshAttemptLabel();
    renderFights();
  } catch {
    select.value = previous;
  }
}

// ---------------------------------------------------------------------------
// Boss fights tab
// ---------------------------------------------------------------------------

/** Caught Pokemon for this attempt, in route order. */
function box() {
  return state.routes
    .filter((r) => state.catches.has(r.id))
    .map((r) => ({ ...state.catches.get(r.id), routeName: r.name }));
}

function teamSlots(fight) {
  const slots = Array(TEAM_SIZE).fill(null);
  for (const m of fight?.members ?? []) slots[m.slot - 1] = m.catch_id;
  return slots;
}

function renderFights() {
  const mons = box();
  $("#empty-box").hidden = mons.length > 0;
  $("#fights-body").replaceChildren(...state.bosses.map((boss) => renderFightRow(boss, mons)));
}

function renderFightRow(boss, mons) {
  const fight = state.fights.get(boss.id);
  const slots = teamSlots(fight);
  const row = el("tr", { "data-boss": boss.id },
    el("td", {}, boss.name),
    el("td", { class: "cap" }, boss.level_cap ? `Lv ${boss.level_cap}` : ""));

  const slotSelects = slots.map((catchId, i) => {
    const taken = new Set(slots.filter((id, j) => id !== null && j !== i));
    const select = el("select", { class: "slot", "aria-label": `${boss.name} slot ${i + 1}` },
      el("option", { value: "" }, "—"),
      ...mons.map((m) => el("option", { value: m.id, disabled: taken.has(m.id) },
        `${m.pokemon} (${m.routeName})`)));
    select.value = catchId ?? "";
    select.classList.toggle("filled", catchId !== null);
    return select;
  });

  const result = el("select", { class: `result ${fight?.result ?? ""}`, "aria-label": `${boss.name} result` },
    el("option", { value: "" }, "—"),
    el("option", { value: "won" }, "Won"),
    el("option", { value: "lost" }, "Lost"));
  result.value = fight?.result ?? "";

  const onChange = () => onFightChange(boss, slotSelects, result, row);
  for (const s of slotSelects) {
    s.addEventListener("change", onChange);
    row.append(el("td", {}, s));
  }
  result.addEventListener("change", onChange);
  row.append(el("td", {}, result));
  return row;
}

async function onFightChange(boss, slotSelects, result, row) {
  const payload = {
    members: slotSelects.map((s) => (s.value ? Number(s.value) : null)),
    result: result.value || null,
  };
  const attemptId = state.attempt.id;
  try {
    const { fight } = await save(() =>
      api("PUT", `/attempts/${attemptId}/fights/${boss.id}`, payload));
    if (state.attempt?.id !== attemptId) return;  // user switched attempts mid-save
    if (fight) state.fights.set(boss.id, fight);
    else state.fights.delete(boss.id);
  } catch { /* fall through: re-render from last saved state */ }
  if (state.attempt?.id === attemptId) row.replaceWith(renderFightRow(boss, box()));
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
  storageSet("tab", name);
}

async function boot() {
  try {
    const game = await api("GET", "/game");
    state.routes = game.routes;
    state.bosses = game.bosses;

    for (const btn of document.querySelectorAll(".tabs button")) {
      btn.addEventListener("click", () => showTab(btn.dataset.tab));
    }
    showTab(["encounters", "fights", "notes"].includes(storageGet("tab")) ? storageGet("tab") : "encounters");

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
