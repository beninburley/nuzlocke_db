"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  routes: [],            // [{id, name, options: [{method, pokemon, rate, levels}]}]
  battles: [],           // [{id, name, location, level_cap, group_id, split, tags}] in game order
  sprites: {},           // species -> sprite url (pokeapi.co)
  evolutions: {},        // species -> its evolutionary line (species names)
  natures: [],
  statuses: [],
  ivStats: [],           // ["hp", "atk", "def", "spa", "spd", "spe"]
  attempts: [],          // [{id, number, notes, catch_count}]
  attempt: null,         // currently selected attempt
  // Box Pokemon and battle copies share one shape:
  // {species, level, ability, nature, item, moves: [4], ivs: {hp, ...}, status}
  catches: new Map(),    // route_id -> box Pokemon + {id, route_id, pokemon (what was caught)}
  // battle_id -> {id, battle_id, result, trainer (enemy team's key or null),
  //   members: [copy + {id, slot, catch_id}], kos: [{member (copy id), enemy (slot), by}]}
  fights: new Map(),
  battleId: null,        // battle shown on the Trainer Battles tab
  boxId: null,           // box Pokemon shown on the Box tab
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

const SVG_NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}, ...children) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
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
  renderBox();
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
    sprite(current.species), el("span", { class: "mon-name" }, current.species),
    current.species !== current.pokemon ? el("span", { class: "mon-route" }, `caught as ${current.pokemon}`) : "",
    statusBadge(current.status));
  change.addEventListener("click", () => openCatchPicker(route));
  const remove = el("button", { type: "button", class: "catch-remove", "aria-label": `Remove ${current.species} from ${route.name}` }, "×");
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
    pickCatch(route, opt.pokemon);
  });
  return card;
}

/** Record the catch (if it changed), then offer its details popup. */
async function pickCatch(route, pokemon) {
  let mon = state.catches.get(route.id);
  if (mon?.pokemon !== pokemon) mon = await saveCatch(route, pokemon);
  if (!mon) return;
  openDetailsDialog({
    title: `${route.name}: ${mon.species}`,
    subtitle: "Fill in what you know, or skip and do it later on the Box tab.",
    mon,
    saveLabel: "Save",
    cancelLabel: "Skip",
    onSave: (fields) => saveCatchDetails(mon.id, fields),
  });
}

async function removeCatch(route) {
  const current = state.catches.get(route.id);
  if (!current) return;
  const teams = [...state.fights.values()].filter((f) => f.members.some((m) => m.catch_id === current.id)).length;
  const hasDetails = !sameDetails(current, { ...emptyDetails(), species: current.species });
  if ((teams || hasDetails) && !confirm(
    `Remove ${current.species} from ${route.name}? Its box details are deleted.` +
    (teams ? ` The ${teams} battle${teams > 1 ? "s" : ""} it was used in keep their copy.` : ""))) {
    return;
  }
  await saveCatch(route, null);
}

/** Set (or clear, with null) a route's catch. Returns the saved box Pokemon, or null. */
async function saveCatch(route, pokemon) {
  const attemptId = state.attempt.id;
  try {
    const { catch: saved } = await save(() =>
      api("PUT", `/attempts/${attemptId}/catches/${route.id}`, { pokemon }));
    if (state.attempt?.id !== attemptId) return null;  // user switched attempts mid-save
    if (saved) state.catches.set(route.id, saved);
    else state.catches.delete(route.id);  // battles keep their copies (catch_id becomes null)
    if (!saved) {
      const data = await api("GET", `/attempts/${attemptId}`);
      state.fights = new Map(data.fights.map((f) => [f.battle_id, f]));
    }
    refreshCatchCell(route);
    refreshAttemptLabel();
    renderBox();
    renderFightView();
    return saved;
  } catch {
    return null;  // save() already reported the error; the cell still shows the saved state
  }
}

/** Save a box Pokemon's details (or evolve it). Battle copies are unaffected. */
async function saveCatchDetails(catchId, fields) {
  const attemptId = state.attempt.id;
  const { catch: saved } = await save(() => api("PATCH", `/catches/${catchId}`, fields));
  if (state.attempt?.id !== attemptId) return saved;
  state.catches.set(saved.route_id, saved);
  refreshCatchCell(state.routes.find((r) => r.id === saved.route_id));
  renderBoxGrid();
  // Refresh the Box tab's editor too, unless it's holding unsaved edits.
  if (saved.id === state.boxId && !boxEditor?.isDirty()) renderBoxDetail();
  renderFightView();
  return saved;
}

// ---------------------------------------------------------------------------
// Pokemon details: the editor shared by the Box tab, the new-catch popup and
// battle copies, plus the Evolve popup
// ---------------------------------------------------------------------------

const IV_LABELS = { hp: "HP", atk: "Atk", def: "Def", spa: "SpA", spd: "SpD", spe: "Spe" };

function emptyDetails() {
  return {
    level: null, ability: null, nature: null, item: null, status: "OK",
    moves: [null, null, null, null], ivs: Object.fromEntries(state.ivStats.map((s) => [s, null])),
  };
}

/** Whether two Pokemon (box or copy) have identical details, species included. */
function sameDetails(a, b) {
  return a.species === b.species && a.level === b.level && a.ability === b.ability
    && a.nature === b.nature && a.item === b.item && a.status === b.status
    && a.moves.every((m, i) => m === b.moves[i])
    && state.ivStats.every((stat) => a.ivs[stat] === b.ivs[stat]);
}

function catchById(id) {
  for (const mon of state.catches.values()) if (mon.id === id) return mon;
  return null;
}

const routeName = (routeId) => state.routes.find((r) => r.id === routeId)?.name ?? "";

function statusBadge(status) {
  return status && status !== "OK" ? el("span", { class: `status-badge ${status.toLowerCase()}` }, status) : "";
}

/** The status badge for a Pokemon shown with monSprite, which stamps "Fainted" on the sprite itself. */
const spriteStatusBadge = (status) => statusBadge(status === "Fainted" ? null : status);

/**
 * A form for a Pokemon's details. `onSave(fields)` and `onEvolve(species)`
 * return promises; evolving saves straight away, other edits wait for Save.
 */
function pokemonEditor(mon, { subtitle, saveLabel = "Save", onSave, onEvolve, onCancel, cancelLabel }) {
  let species = mon.species;
  const text = (value, list, placeholder) =>
    el("input", { type: "text", value: value ?? "", list, placeholder, maxlength: "40", autocomplete: "off" });
  const number = (value, min, max, placeholder) =>
    el("input", { type: "number", value: value ?? "", min: String(min), max: String(max), step: "1", placeholder });
  const select = (options, value, blank) => {
    const node = el("select", {},
      ...(blank ? [el("option", { value: "" }, blank)] : []),
      ...options.map((o) => el("option", { value: o }, o)));
    node.value = value ?? "";
    return node;
  };
  const field = (label, input, className = "") =>
    el("label", { class: `field ${className}` }, el("span", { class: "field-label" }, label), input);

  const level = number(mon.level, 1, 100, "?");
  const status = select(state.statuses, mon.status);
  const nature = select(state.natures, mon.nature, "—");
  const ability = text(mon.ability, "dl-abilities", "Ability");
  const item = text(mon.item, "dl-items", "None");
  const moves = mon.moves.map((m, i) => text(m, "dl-moves", `Move ${i + 1}`));
  const ivs = Object.fromEntries(state.ivStats.map((stat) => [stat, number(mon.ivs[stat], 0, 31, "?")]));

  const headSprite = el("span", { class: "editor-sprite" });
  const headName = el("h3", { class: "editor-species" }, species);
  const evolve = el("button", { type: "button", class: "evolve-button" }, "Evolve…");
  const refreshHead = () => {
    headSprite.replaceChildren(monSprite(species, mon.status));
    headName.textContent = species;
    evolve.hidden = (state.evolutions[species] ?? []).length < 2;
  };
  evolve.addEventListener("click", () => openEvolvePicker(species, async (next) => {
    await onEvolve(next);
    species = next;
    refreshHead();
  }));
  refreshHead();

  const values = () => {
    const int = (input) => (input.value === "" ? null : Number(input.value));
    return {
      level: int(level),
      status: status.value,
      nature: nature.value || null,
      ability: ability.value.trim() || null,
      item: item.value.trim() || null,
      moves: moves.map((m) => m.value.trim() || null),
      ivs: Object.fromEntries(Object.entries(ivs).map(([stat, input]) => [stat, int(input)])),
    };
  };
  const initial = JSON.stringify(values());

  const saveButton = el("button", { type: "submit", class: "primary" }, saveLabel);
  const form = el("form", { class: "pokemon-editor" },
    el("div", { class: "editor-head" }, headSprite,
      el("div", { class: "editor-title" }, headName, subtitle ? el("p", { class: "muted" }, subtitle) : ""),
      evolve),
    el("div", { class: "editor-row" },
      field("Level", level, "narrow"), field("Status", status), field("Nature", nature)),
    el("div", { class: "editor-row" }, field("Ability", ability), field("Held item", item)),
    el("div", { class: "field" }, el("span", { class: "field-label" }, "Moves"),
      el("div", { class: "moves-grid" }, ...moves)),
    el("div", { class: "field" }, el("span", { class: "field-label" }, "IVs"),
      el("div", { class: "ivs-grid" }, ...state.ivStats.map((stat) =>
        el("label", { class: "iv" }, el("span", {}, IV_LABELS[stat]), ivs[stat])))),
    el("div", { class: "editor-actions" },
      onCancel ? (() => {
        const cancel = el("button", { type: "button" }, cancelLabel ?? "Cancel");
        cancel.addEventListener("click", onCancel);
        return cancel;
      })() : "",
      saveButton));
  form.addEventListener("submit", async (e) => {
    e.preventDefault();  // only fires once the inputs pass their min/max checks
    saveButton.disabled = true;
    try {
      await onSave(values());
    } catch { /* save() already showed the error */ } finally {
      saveButton.disabled = false;
    }
  });
  return { node: form, isDirty: () => JSON.stringify(values()) !== initial };
}

/** The details popup: a new catch (Save / Skip) or a battle copy (Save / Cancel). */
function openDetailsDialog({ title, subtitle, mon, saveLabel, cancelLabel, onSave, onEvolve }) {
  const dialog = $("#details-dialog");
  const editor = pokemonEditor(mon, {
    subtitle,
    saveLabel,
    cancelLabel,
    onCancel: () => dialog.close(),
    onEvolve: onEvolve ?? ((species) => onSave({ species })),
    onSave: async (fields) => {
      await onSave(fields);
      dialog.close();
    },
  });
  $("#details-title").textContent = title;
  $("#details-body").replaceChildren(editor.node);
  dialog.showModal();
}

/** Pick any member of `species`' evolutionary line. */
function openEvolvePicker(species, onPick) {
  const dialog = $("#evolve-picker");
  const line = state.evolutions[species] ?? [species];
  $("#evolve-title").textContent = `Evolve or devolve ${species}`;
  $("#evolve-body").replaceChildren(el("div", { class: "picker-grid" }, ...line.map((member) => {
    const card = el("button", { type: "button", class: "pick-card", "aria-pressed": String(member === species) },
      sprite(member), el("span", { class: "mon-name" }, member),
      el("span", { class: "mon-route" }, member === species ? "current" : ""));
    card.addEventListener("click", async () => {
      dialog.close();
      if (member !== species) await onPick(member).catch(() => {});
    });
    return card;
  })));
  dialog.showModal();
}

// ---------------------------------------------------------------------------
// Box tab: the box on the right, the selected Pokemon's details on the left
// ---------------------------------------------------------------------------

let boxEditor = null;  // the open editor, to warn before discarding unsaved edits

function renderBox() {
  if (!state.attempt) return;
  renderBoxGrid();
  renderBoxDetail();
}

function renderBoxGrid() {
  const mons = box();
  if (!mons.some((m) => m.id === state.boxId)) state.boxId = mons[0]?.id ?? null;
  $("#box-tab-count").textContent = `(${mons.length} caught)`;
  $("#box-tab-empty").hidden = mons.length > 0;
  $("#box-tab-grid").replaceChildren(...mons.map((mon) => {
    const node = el("button", {
      type: "button",
      class: `box-mon${mon.status === "Fainted" ? " fainted" : ""}`,
      "aria-current": mon.id === state.boxId ? "true" : undefined,
      title: `${mon.species} (${mon.routeName})`,
    }, ...monLabel(mon), spriteStatusBadge(mon.status));
    node.addEventListener("click", () => selectBoxMon(mon.id));
    return node;
  }));
}

function selectBoxMon(id) {
  if (id === state.boxId) return;
  if (boxEditor?.isDirty() && !confirm("Discard your unsaved changes?")) return;
  state.boxId = id;
  renderBox();
}

function renderBoxDetail() {
  const mon = catchById(state.boxId);
  if (!mon) {
    boxEditor = null;
    $("#box-detail").replaceChildren(el("p", { class: "hint" }, "Pick a Pokémon from your box to see and edit its details."));
    return;
  }
  boxEditor = pokemonEditor(mon, {
    subtitle: [mon.species !== mon.pokemon && `Caught as ${mon.pokemon}`, routeName(mon.route_id)]
      .filter(Boolean).join(" · "),
    onEvolve: (species) => saveCatchDetails(mon.id, { species }),
    onSave: async (fields) => {
      await saveCatchDetails(mon.id, fields);
      renderBoxDetail();  // start fresh from what was saved
    },
  });
  $("#box-detail").replaceChildren(boxEditor.node);
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

/** A fight's team as six slots of battle copies (null = empty). */
function teamSlots(fight) {
  const slots = Array(TEAM_SIZE).fill(null);
  for (const m of fight?.members ?? []) slots[m.slot - 1] = m;
  return slots;
}

/** A new battle copy of a box Pokemon, as it is now (saved when the team is). */
function freshCopy(mon) {
  const { id, route_id, pokemon, routeName: _, ...details } = mon;
  return { ...details, catch_id: id };
}

/** Whether a battle copy no longer matches its box Pokemon (or that is gone). */
function copyChanged(member) {
  const source = member.catch_id === null ? null : catchById(member.catch_id);
  return !source || !sameDetails(member, source);
}

const battleById = (id) => state.battles.find((b) => b.id === id);
const currentBattle = () => battleById(state.battleId);
const currentSlots = () => teamSlots(state.fights.get(state.battleId));
// The level-cap battle ending each split. (A split can have more than one
// level-cap battle: the Museum grunts and Tate & Liza are fought one at a time.)
const splitEnds = () => state.battles.filter((b) => b.split !== null);

function sprite(species) {
  const fallback = () => el("span", { class: "sprite sprite-missing", "aria-hidden": "true" }, species.slice(0, 2));
  const url = state.sprites[species];
  if (!url) return fallback();
  const img = el("img", { class: "sprite", src: url, alt: "", draggable: "false" });
  img.addEventListener("error", () => img.replaceWith(fallback()), { once: true });
  return img;
}

/** A Pokemon's sprite; greyed out with a diagonal "Fainted" stamp if it has fainted. */
function monSprite(species, status) {
  if (status !== "Fainted") return sprite(species);
  return el("span", { class: "fainted-sprite", title: `${species} has fainted` },
    sprite(species), el("span", { class: "fainted-stamp", "aria-hidden": "true" }, "Fainted"));
}

function monLabel(mon) {
  return [monSprite(mon.species, mon.status),
    el("span", { class: "mon-name" }, mon.species),
    el("span", { class: "mon-route" }, [mon.level && `Lv ${mon.level}`, mon.routeName].filter(Boolean).join(" · "))];
}

function defaultBattleId() {
  const stored = Number(storageGet("battleId"));
  if (state.battles.some((b) => b.id === stored)) return stored;
  // Otherwise the first level-cap fight with nothing recorded yet.
  const bosses = state.battles.filter((b) => b.level_cap !== null);
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
  renderKoStats();
}

// --- battle list (drawer) ------------------------------------------------------

/**
 * One dropdown per split: the trainers leading up to a level-cap battle, in
 * game order, ending with the level-cap battle itself.
 */
function renderBattleList() {
  const query = $("#battle-filter").value.trim().toLowerCase();
  const matches = (b) => !query || `${b.name} ${b.location ?? ""}`.toLowerCase().includes(query);
  const groups = splitEnds().map((boss) => {
    const battles = [...state.battles.filter((b) => b.group_id === boss.id), boss];
    const shown = battles.filter(matches);
    if (!shown.length) return null;
    const open = Boolean(query) || openGroups.has(boss.id);
    const result = splitResult(battles);
    const toggle = el("button", {
      type: "button",
      class: `group-toggle ${result.status ?? ""}`,
      "aria-expanded": String(open),
    },
      el("span", { class: "chevron", "aria-hidden": "true" }, "▸"),
      el("span", { class: "group-name" }, `${boss.split} Split`),
      el("span", { class: "battle-status", title: result.title }, { won: "✓", lost: "✗" }[result.status] ?? ""),
      el("span", { class: "group-meta" }, `Level cap ${boss.level_cap} · ${battles.length} battles`));
    toggle.addEventListener("click", () => {
      if (openGroups.has(boss.id)) openGroups.delete(boss.id);
      else openGroups.add(boss.id);
      renderBattleList();
    });
    return el("li", { class: "battle-group" },
      toggle,
      el("ol", { class: "trainer-list", hidden: !open }, ...shown.map(battleItem)));
  }).filter(Boolean);
  $("#battle-list").replaceChildren(...groups);
  $("#no-matches").hidden = groups.length > 0;
}

/** A split is lost if any of its battles was lost, and won once all its level-cap battles are won. */
function splitResult(battles) {
  const lost = battles.filter((b) => state.fights.get(b.id)?.result === "lost");
  if (lost.length) return { status: "lost", title: `Lost: ${lost.map((b) => b.name).join(", ")}` };
  const bosses = battles.filter((b) => b.level_cap !== null);
  if (bosses.every((b) => state.fights.get(b.id)?.result === "won")) return { status: "won", title: "Won" };
  return { status: null, title: "Not finished" };
}

/** A battle in the list, with a KO button once it has a result. */
function battleItem(battle) {
  const fight = state.fights.get(battle.id);
  const item = el("li", { class: "battle-item" },
    battleButton(battle, battle.level_cap !== null ? "boss-item" : "trainer-item"));
  if (fight?.result) {
    const kos = fight.kos ?? [];
    const ours = kos.filter((k) => k.by === "player").length;
    const button = el("button", {
      type: "button",
      class: `ko-edit${kos.length ? " has-kos" : ""}`,
      title: kos.length ? `Edit KOs (${ours} by your team, ${kos.length - ours} by the enemy)` : "Record KOs",
      "aria-label": `KOs for ${battle.name}`,
    }, koIcon());
    button.addEventListener("click", () => {
      selectBattle(battle.id);
      openKoTracker(battle.id);
    });
    item.classList.add("with-ko");
    item.append(button);
  }
  return item;
}

/** Green arrow up, red arrow down: the KO tracker's two kinds of arrow. */
function koIcon() {
  return svgEl("svg", { class: "ko-icon", viewBox: "0 0 16 16", width: "16", height: "16", "aria-hidden": "true" },
    svgEl("path", { class: "up", d: "M5 13V3.5M2.2 6.3 5 3.5l2.8 2.8" }),
    svgEl("path", { class: "down", d: "M11 3v9.5m-2.8-2.8 2.8 2.8 2.8-2.8" }));
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

  // The split's level cap sits above the name, for regular trainers too.
  const split = battle.group_id !== null ? battleById(battle.group_id) : battle.split !== null ? battle : null;
  $("#focus-cap").hidden = !split;
  $("#focus-cap").replaceChildren(...(split ? [
    el("strong", { class: "cap-badge" }, `Level cap ${split.level_cap}`),
    el("span", { class: "muted" }, `${split.split} Split`),
  ] : []));
  $("#focus-name").textContent = battle.name;
  $("#focus-sub").textContent = [battle.location, ...battle.tags.filter((t) => !HIDDEN_TAGS.has(t))]
    .filter(Boolean).join(" · ");
  for (const btn of document.querySelectorAll(".result-toggle button")) {
    btn.setAttribute("aria-pressed", fight?.result === btn.dataset.result);
  }
  $("#ko-open").hidden = !fight?.result;

  $("#team-count").textContent = `${slots.filter(Boolean).length}/${TEAM_SIZE}`;
  $("#team-changed").hidden = !slots.some((m) => m && copyChanged(m));
  $("#team-grid").replaceChildren(...slots.map((member, i) => teamSlot(i, member)));

  $("#box-count").textContent = `(${mons.length} caught)`;
  $("#empty-box").hidden = mons.length > 0;
  $("#box-grid").replaceChildren(...mons.map((m) => boxMon(m, slots.findIndex((s) => s?.catch_id === m.id))));
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

/** Which trainer to show first: the enemy team the fight's KOs were recorded against, else the first. */
function savedTrainerIndex(battleId, detail) {
  const key = state.fights.get(battleId)?.trainer;
  return Math.max(0, detail.trainers.findIndex((t) => t.key === key));
}

function renderEnemy() {
  const battleId = state.battleId;
  const detail = battleDetails.get(battleId);
  const index = detail ? Math.min(trainerChoice.get(battleId) ?? savedTrainerIndex(battleId, detail), detail.trainers.length - 1) : 0;
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

function teamSlot(index, member) {
  const slot = el("div", { class: `team-slot${member ? " filled" : ""}` });
  if (member) {
    const source = member.catch_id === null ? null : catchById(member.catch_id);
    const remove = el("button", { type: "button", class: "remove", "aria-label": `Remove ${member.species} from the team` }, "×");
    remove.addEventListener("click", () => setSlot(index, null));
    slot.append(
      monSprite(member.species, member.status),
      el("span", { class: "mon-name" }, member.species),
      el("span", { class: "mon-route" },
        [member.level && `Lv ${member.level}`, source ? routeName(source.route_id) : "no longer in box"]
          .filter(Boolean).join(" · ")),
      spriteStatusBadge(member.status),
      copyChanged(member) ? el("span", { class: "changed-tag", title: "This copy differs from the Pokémon in your box" }, "changed") : "",
      remove);
    slot.tabIndex = 0;
    slot.title = `${member.species}: click to see or edit this battle's copy; drag to swap slots or back to the box to remove`;
    const open = () => openCopyEditor(member);
    slot.addEventListener("click", (e) => { if (!e.target.closest(".remove")) open(); });
    slot.addEventListener("keydown", (e) => {
      if (e.target === slot && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); open(); }
    });
    makeDraggable(slot, { catchId: member.catch_id, fromSlot: index });
  } else {
    slot.append(el("span", { class: "slot-empty" }, `Slot ${index + 1}`));
  }
  makeDropTarget(slot, (drag) => (drag.fromSlot === null ? addToTeam(drag.catchId, index) : moveSlot(drag.fromSlot, index)));
  return slot;
}

function openCopyEditor(member) {
  if (!member.id) return setStatus("Still saving this team; try again in a moment", "error");
  const source = member.catch_id === null ? null : catchById(member.catch_id);
  openDetailsDialog({
    title: `${currentBattle().name}: ${member.species}`,
    subtitle: "This battle's copy. Changes here don't affect your box" +
      (source ? ` (currently ${source.species}${source.level ? ` Lv ${source.level}` : ""}).` : "."),
    mon: member,
    saveLabel: "Save copy",
    onSave: (fields) => saveCopy(member.id, fields),
  });
}

function boxMon(mon, teamIndex) {
  const onTeam = teamIndex !== -1;
  const node = el("div", {
    class: `box-mon${onTeam ? " on-team" : ""}${mon.status === "Fainted" ? " fainted" : ""}`,
    role: "button",
    tabindex: "0",
    "aria-pressed": String(onTeam),
    title: `${mon.species} (${mon.routeName})${onTeam ? ": on the team" : ""}`,
  }, ...monLabel(mon), spriteStatusBadge(mon.status));
  const toggle = () => {
    if (onTeam) return setSlot(teamIndex, null);
    const empty = currentSlots().indexOf(null);
    if (empty === -1) return setStatus("Team is full: drag onto a slot to replace someone", "error");
    addToTeam(mon.id, empty);
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

const currentResult = () => state.fights.get(state.battleId)?.result ?? null;

/** Put a box Pokemon into a slot as a fresh copy. If it's already on the team, move its copy. */
function addToTeam(catchId, index) {
  const slots = currentSlots();
  const from = slots.findIndex((m) => m?.catch_id === catchId);
  if (from !== -1) return moveSlot(from, index);
  const mon = catchById(catchId);
  if (!mon) return;
  slots[index] = freshCopy(mon);
  saveFight(slots, currentResult());
}

/** Swap two team slots; the copies themselves don't change. */
function moveSlot(from, to) {
  if (from === to) return;
  const slots = currentSlots();
  [slots[from], slots[to]] = [slots[to], slots[from]];
  saveFight(slots, currentResult());
}

function setSlot(index, member) {
  const slots = currentSlots();
  slots[index] = member;
  saveFight(slots, currentResult());
}

/** Record (or clear) the result. Recording one opens the KO tracker. */
function toggleResult(result) {
  const next = currentResult() === result ? null : result;
  saveFight(currentSlots(), next);
  if (next) openKoTracker(state.battleId);
}

/** Apply a fight change immediately, then save it in the background. */
function saveFight(slots, result) {
  const attemptId = state.attempt.id;
  const battleId = state.battleId;
  const members = slots.flatMap((m, i) => (m ? [{ ...m, slot: i + 1 }] : []));
  // Saved copies are kept by id; new ones are copied from their box Pokemon.
  const payload = slots.map((m) => (m ? (m.id ? { id: m.id } : { catch_id: m.catch_id }) : null));
  if (members.length || result) {
    const previous = state.fights.get(battleId);
    const kept = new Set(members.map((m) => m.id));
    state.fights.set(battleId, {
      trainer: null, ...previous, battle_id: battleId, result, members,
      kos: (previous?.kos ?? []).filter((k) => kept.has(k.member)),  // a removed copy's KOs go with it
    });
  } else {
    state.fights.delete(battleId);
  }
  renderFightView();

  const edit = (fightEdits.get(battleId) ?? 0) + 1;
  fightEdits.set(battleId, edit);
  saveChain = saveChain.then(async () => {
    try {
      const { fight } = await save(() =>
        api("PUT", `/attempts/${attemptId}/fights/${battleId}`, { members: payload, result }));
      // Keep the optimistic state if the user switched attempts or edited again since.
      if (state.attempt?.id !== attemptId || fightEdits.get(battleId) !== edit) return;
      if (fight) state.fights.set(battleId, fight);
      else state.fights.delete(battleId);
    } catch {
      await resync(attemptId);
    }
  });
}

/** After a failed save: reload the attempt so the page shows what the server actually has. */
async function resync(attemptId) {
  if (state.attempt?.id !== attemptId) return;
  const data = await api("GET", `/attempts/${attemptId}`).catch(() => null);
  if (!data || state.attempt?.id !== attemptId) return;
  state.catches = new Map(data.catches.map((c) => [c.route_id, c]));
  state.fights = new Map(data.fights.map((f) => [f.battle_id, f]));
  renderEncounters();
  renderBox();
  renderFightView();
  if (koSession?.attemptId === attemptId && $("#ko-dialog").open) {
    const fight = state.fights.get(koSession.battleId);
    if (fight?.id === koSession.fightId) {
      koSession.kos = fight.kos.map((k) => ({ ...k }));
      renderKoTracker();
    }
  }
}

/** Save one battle's copy. Queued behind pending team saves so their replies can't undo it. */
async function saveCopy(memberId, fields) {
  const attemptId = state.attempt.id;
  const battleId = state.battleId;
  const run = saveChain.then(() => save(() => api("PATCH", `/fight-members/${memberId}`, fields)));
  saveChain = run.catch(() => {});
  const { member } = await run;
  const fight = state.fights.get(battleId);
  if (state.attempt?.id === attemptId && fight) {
    fight.members = fight.members.map((m) => (m.id === member.id ? member : m));
    renderFightView();
  }
  return member;
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
// KO tracker: the enemy team above your team, with a dot between each. An
// arrow from your Pokemon to an enemy (green) is a KO by your Pokemon; one from
// an enemy to your Pokemon (red) is a KO by the enemy. Changes save as you go.
// ---------------------------------------------------------------------------

let koSession = null;  // the fight open in the KO tracker (see openKoTracker)
let koOpens = 0;       // to ignore a load that finishes after the tracker was reopened

async function openKoTracker(battleId) {
  const dialog = $("#ko-dialog");
  const attemptId = state.attempt.id;
  const open = ++koOpens;
  koSession = null;
  $("#ko-title").textContent = `KOs: ${battleById(battleId).name}`;
  $("#ko-trainers").replaceChildren();
  $("#ko-summary").textContent = "";
  $("#ko-board").replaceChildren(el("p", { class: "hint" }, "Loading…"));
  if (!dialog.open) dialog.showModal();

  let detail;
  try {
    // Wait for pending team/result saves, so every team member has its copy id.
    [detail] = await Promise.all([loadBattle(battleId), saveChain]);
  } catch (err) {
    setStatus(`Error: ${err.message}`, "error");
    dialog.close();
    return;
  }
  if (open !== koOpens || !dialog.open || state.attempt?.id !== attemptId) return;
  const fight = state.fights.get(battleId);
  if (!fight?.id) {
    $("#ko-board").replaceChildren(el("p", { class: "hint warn" }, "This fight couldn't be saved, so its KOs can't be either."));
    return;
  }
  const enemies = detail.trainers.filter((t) => !t.tags.includes("Tag Partner"));
  const shown = detail.trainers[trainerChoice.get(battleId) ?? savedTrainerIndex(battleId, detail)];
  koSession = {
    attemptId,
    battleId,
    fightId: fight.id,
    detail,
    enemies,                       // alternative enemy teams (the rival's starter variants)
    trainer: enemies.find((t) => t.key === fight.trainer) ?? (enemies.includes(shown) ? shown : enemies[0]),
    party: teamSlots(fight),       // six slots of battle copies (null = empty)
    kos: fight.kos.map((k) => ({ ...k })),
    armed: null,                   // {side, index}: the first dot clicked, waiting for the second
    drag: null,                    // {side, index, x, y, moved} while dragging from a dot
  };
  renderKoTracker();
}

const koName = (side, index) =>
  (side === "enemy" ? koSession.trainer?.pokemon[index] : koSession.party[index])?.species ?? "?";

function isKnockedOut(side, index) {
  if (side === "enemy") return koSession.kos.some((k) => k.by === "player" && k.enemy === index + 1);
  const id = koSession.party[index]?.id;
  return koSession.kos.some((k) => k.by === "enemy" && k.member === id);
}

function renderKoTracker() {
  const s = koSession;
  const labels = trainerLabels(s.enemies);
  $("#ko-trainers").replaceChildren(...(s.enemies.length > 1 ? s.enemies.map((t, i) => {
    const tab = el("button", { type: "button", "aria-pressed": String(t === s.trainer), title: t.name }, labels[i]);
    tab.addEventListener("click", () => setKoTrainer(t));
    return tab;
  }) : []));

  const enemyTeam = s.trainer?.pokemon ?? [];
  const teamless = !s.party.some(Boolean);
  $("#ko-board").replaceChildren(
    teamless ? el("p", { class: "hint warn" }, "Add your team to this battle first to record who knocked out whom.") : "",
    el("h3", { class: "ko-row-label" }, s.trainer ? s.trainer.name : "Enemy team"),
    el("div", { class: "ko-row enemy" }, ...Array.from({ length: TEAM_SIZE }, (_, i) => koColumn("enemy", i, enemyTeam[i]))),
    el("div", { class: "ko-row party" }, ...s.party.map((m, i) => koColumn("party", i, m))),
    el("h3", { class: "ko-row-label" }, "Your team"),
    svgEl("svg", { class: "ko-arrows" }));
  drawKoArrows();
  renderKoSummary();
}

function renderKoSummary() {
  const s = koSession;
  const summary = $("#ko-summary");
  if (s.armed) {
    summary.className = "ko-armed-hint";
    summary.textContent = s.armed.side === "party"
      ? `Now click the enemy ${koName("party", s.armed.index)} knocked out.`
      : `Now click the Pokémon ${koName("enemy", s.armed.index)} knocked out.`;
    return;
  }
  const ours = s.kos.filter((k) => k.by === "player").length;
  summary.className = "muted";
  summary.textContent = `${ours} KO${ours === 1 ? "" : "s"} by your team · ${s.kos.length - ours} by the enemy`;
}

/** One Pokemon with its dot: below it for the enemy, above it for your team. */
function koColumn(side, index, mon) {
  const card = el("div", { class: `ko-mon ${side}${mon ? "" : " empty"}${mon && isKnockedOut(side, index) ? " knocked-out" : ""}` },
    ...(mon ? [
      monSprite(mon.species, side === "party" ? mon.status : null),
      el("span", { class: "mon-name" }, mon.species),
      el("span", { class: "mon-route" }, mon.level ? `Lv ${mon.level}` : ""),
    ] : [el("span", { class: "slot-empty" }, "—")]));
  const usable = mon && (side === "enemy" || mon.id);
  const armed = koSession.armed?.side === side && koSession.armed.index === index;
  const dot = usable
    ? el("button", {
      type: "button",
      class: `ko-dot ${side}${armed ? " armed" : ""}`,
      "data-side": side,
      "data-index": String(index),
      "aria-pressed": String(armed),
      "aria-label": side === "party" ? `${mon.species}: draw a KO it scored` : `Enemy ${mon.species}: draw a KO it scored`,
    })
    : el("span", { class: "ko-dot-spacer" });
  return el("div", { class: `ko-col ${side}`, "data-side": side, "data-index": String(index) },
    ...(side === "enemy" ? [card, dot] : [dot, card]));
}

/** The arrows, drawn over the board from dot to dot. */
function drawKoArrows() {
  const board = $("#ko-board");
  const svg = board.querySelector(".ko-arrows");
  if (!svg || !koSession) return;
  const frame = board.getBoundingClientRect();
  svg.setAttribute("viewBox", `0 0 ${frame.width} ${frame.height}`);
  const heads = svgEl("defs", {}, ...["player", "enemy"].map((by) =>
    svgEl("marker", { id: `ko-head-${by}`, class: `ko-head ${by}`, viewBox: "0 0 10 10", refX: "7", refY: "5",
      markerWidth: "4", markerHeight: "4", orient: "auto" }, svgEl("path", { d: "M0 0L10 5L0 10z" }))));
  const arrows = koSession.kos.map((k) => {
    const party = dotCenter("party", koSession.party.findIndex((m) => m?.id === k.member));
    const enemy = dotCenter("enemy", k.enemy - 1);
    if (!party || !enemy) return null;
    const [from, to] = k.by === "player" ? [party, enemy] : [enemy, party];
    // An arrow each way between the same two Pokemon (Destiny Bond...): shift both so both show.
    const paired = koSession.kos.some((o) => o !== k && o.member === k.member && o.enemy === k.enemy);
    const partyName = koName("party", koSession.party.findIndex((m) => m?.id === k.member));
    const enemyName = koName("enemy", k.enemy - 1);
    const label = k.by === "player" ? `${partyName} knocked out ${enemyName}` : `${enemyName} knocked out your ${partyName}`;
    return koArrow(from, to, k, paired ? 4 : 0, label);
  }).filter(Boolean);
  svg.replaceChildren(heads, ...arrows);
  if (koSession.drag?.line) svg.append(koSession.drag.line);
}

function dotCenter(side, index) {
  const dot = $(`#ko-board .ko-dot[data-side="${side}"][data-index="${index}"]`);
  if (!dot) return null;
  const frame = $("#ko-board").getBoundingClientRect();
  const r = dot.getBoundingClientRect();
  return { x: r.left + r.width / 2 - frame.left, y: r.top + r.height / 2 - frame.top };
}

function koArrow(from, to, ko, shift, label) {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const length = Math.hypot(dx, dy) || 1;
  const [ux, uy] = [dx / length, dy / length];
  const [nx, ny] = [-uy * shift, ux * shift];
  const gap = 13;  // start and end just outside the dots
  const d = `M${from.x + ux * gap + nx} ${from.y + uy * gap + ny}L${to.x - ux * gap + nx} ${to.y - uy * gap + ny}`;
  const arrow = svgEl("g", { class: `ko-arrow ${ko.by}`, tabindex: "0", role: "button", "aria-label": `${label}. Remove` },
    svgEl("title", {}, `${label} (click to remove)`),
    svgEl("path", { class: "hit", d }),
    svgEl("path", { class: "line", d, "marker-end": `url(#ko-head-${ko.by})` }));
  const remove = () => {
    koSession.kos = koSession.kos.filter((k) => k !== ko);
    saveKos();
  };
  arrow.addEventListener("click", remove);
  arrow.addEventListener("keydown", (e) => {
    if (["Enter", " ", "Delete", "Backspace"].includes(e.key)) {
      e.preventDefault();
      remove();
    }
  });
  return arrow;
}

/** Add the arrow for a KO drawn from one dot to another (of the other side). */
function addKo(from, to) {
  if (from.side === to.side) return;
  const [party, enemy] = from.side === "party" ? [from.index, to.index] : [to.index, from.index];
  const member = koSession.party[party]?.id;
  if (!member || !koSession.trainer?.pokemon[enemy]) return;
  const by = from.side === "party" ? "player" : "enemy";
  // A Pokemon is knocked out once, so a new arrow into it replaces the old one.
  koSession.kos = koSession.kos.filter((k) =>
    !(k.by === by && (by === "player" ? k.enemy === enemy + 1 : k.member === member)));
  koSession.kos.push({ member, enemy: enemy + 1, by });
  saveKos();
}

/** Click one dot, then a dot on the other side: the same as dragging between them. */
function clickKoDot(side, index) {
  const armed = koSession.armed;
  koSession.armed = null;
  if (armed && armed.side !== side) addKo(armed, { side, index });
  else if (!armed || armed.index !== index) koSession.armed = { side, index };
  renderKoTracker();
}

function setKoTrainer(trainer) {
  if (trainer === koSession.trainer) return;
  koSession.trainer = trainer;
  koSession.armed = null;
  koSession.kos = koSession.kos.filter((k) => k.enemy <= trainer.pokemon.length);
  trainerChoice.set(koSession.battleId, koSession.detail.trainers.indexOf(trainer));
  saveKos();
}

/** Show the change straight away, then save it in the background. */
function saveKos() {
  const { attemptId, battleId, fightId } = koSession;
  const body = {
    trainer: koSession.enemies.length > 1 ? koSession.trainer.key : null,
    kos: koSession.kos.map((k) => ({ ...k })),
  };
  const fight = state.fights.get(battleId);
  if (fight?.id === fightId) Object.assign(fight, { trainer: body.trainer, kos: body.kos });
  renderKoTracker();
  renderFightView();
  const run = saveChain.then(() => save(() => api("PUT", `/fights/${fightId}/kos`, body)));
  saveChain = run.catch(() => resync(attemptId));
}

function koDotAt(x, y, fromSide) {
  // Dropping anywhere on a Pokemon of the other side counts, not just on its dot.
  const col = document.elementFromPoint(x, y)?.closest("#ko-board .ko-col");
  if (!col || col.dataset.side === fromSide || !col.querySelector(".ko-dot")) return null;
  return { side: col.dataset.side, index: Number(col.dataset.index) };
}

function setupKoBoard() {
  const board = $("#ko-board");
  board.addEventListener("pointerdown", (e) => {
    const dot = e.target.closest(".ko-dot");
    if (!dot || e.button !== 0 || !koSession) return;
    e.preventDefault();
    dot.setPointerCapture(e.pointerId);
    koSession.drag = { side: dot.dataset.side, index: Number(dot.dataset.index), x: e.clientX, y: e.clientY, moved: false };
  });
  board.addEventListener("pointermove", (e) => {
    const drag = koSession?.drag;
    if (!drag) return;
    if (!drag.moved && Math.hypot(e.clientX - drag.x, e.clientY - drag.y) < 6) return;
    drag.moved = true;
    const start = dotCenter(drag.side, drag.index);
    const frame = board.getBoundingClientRect();
    if (!drag.line) {
      drag.line = svgEl("line", { class: `ko-temp ${drag.side === "party" ? "player" : "enemy"}` });
      board.querySelector(".ko-arrows").append(drag.line);
    }
    for (const [key, value] of Object.entries({ x1: start.x, y1: start.y, x2: e.clientX - frame.left, y2: e.clientY - frame.top })) {
      drag.line.setAttribute(key, value);
    }
    const target = koDotAt(e.clientX, e.clientY, drag.side);
    for (const col of board.querySelectorAll(".ko-col.drop-target")) col.classList.remove("drop-target");
    if (target) board.querySelector(`.ko-col[data-side="${target.side}"][data-index="${target.index}"]`).classList.add("drop-target");
  });
  const finish = (e, dropped) => {
    const drag = koSession?.drag;
    if (!drag) return;
    koSession.drag = null;
    drag.line?.remove();
    if (!dropped) return renderKoTracker();
    if (!drag.moved) return clickKoDot(drag.side, drag.index);
    const target = koDotAt(e.clientX, e.clientY, drag.side);
    koSession.armed = null;
    if (target) addKo(drag, target);
    else renderKoTracker();
  };
  board.addEventListener("pointerup", (e) => finish(e, true));
  board.addEventListener("pointercancel", (e) => finish(e, false));
  // Keyboard: Enter/Space on a dot works like clicking it (pointer clicks are handled above).
  board.addEventListener("click", (e) => {
    const dot = e.target.closest(".ko-dot");
    if (!dot || e.detail !== 0 || !koSession) return;
    const { side, index } = dot.dataset;
    clickKoDot(side, Number(index));
    $(`#ko-board .ko-dot[data-side="${side}"][data-index="${index}"]`)?.focus();
  });
  new ResizeObserver(() => drawKoArrows()).observe(board);
  $("#ko-clear").addEventListener("click", () => {
    if (!koSession?.kos.length || !confirm("Remove every arrow for this fight?")) return;
    koSession.kos = [];
    koSession.armed = null;
    saveKos();
  });
  $("#ko-done").addEventListener("click", () => $("#ko-dialog").close());
  // The close event arrives asynchronously: by then the tracker may be open again for another fight.
  $("#ko-dialog").addEventListener("close", (e) => { if (!e.currentTarget.open) koSession = null; });
  $("#ko-open").addEventListener("click", () => openKoTracker(state.battleId));
}

// ---------------------------------------------------------------------------
// KO Analytics tab: KOs per Pokemon this attempt, as a horizontal bar chart
// ---------------------------------------------------------------------------

function renderKoStats() {
  if (!state.attempt) return;
  const order = new Map(state.routes.map((r, i) => [r.id, i]));
  const rows = new Map();  // box Pokemon (or a copy whose box Pokemon is gone) -> its KOs
  for (const fight of state.fights.values()) {
    const battle = battleById(fight.battle_id);
    for (const k of fight.kos ?? []) {
      if (k.by !== "player") continue;
      const member = fight.members.find((m) => m.id === k.member);
      if (!member) continue;
      const mon = member.catch_id === null ? null : catchById(member.catch_id);
      const key = mon ? `box:${mon.id}` : `gone:${member.species}`;
      if (!rows.has(key)) {
        rows.set(key, { mon, species: mon?.species ?? member.species, kos: 0, battles: new Map(),
          order: mon ? order.get(mon.route_id) : Infinity });
      }
      const row = rows.get(key);
      row.kos++;
      const name = battle?.name ?? "Unknown battle";
      row.battles.set(name, (row.battles.get(name) ?? 0) + 1);
    }
  }
  const ranked = [...rows.values()].sort((a, b) => b.kos - a.kos || a.order - b.order);
  const total = ranked.reduce((sum, row) => sum + row.kos, 0);
  const most = ranked[0]?.kos ?? 1;
  $("#ko-stats-total").textContent = total
    ? `(${total} KO${total === 1 ? "" : "s"} by ${ranked.length} Pokémon)` : "";
  $("#ko-stats-empty").hidden = ranked.length > 0;
  $("#ko-chart").replaceChildren(...ranked.map((row, i) => {
    const battles = [...row.battles].map(([name, n]) => (n > 1 ? `${name} ×${n}` : name));
    return el("li", { class: "ko-chart-row", title: `${row.species}: ${battles.join(", ")}` },
      el("span", { class: "ko-chart-rank" }, String(i + 1)),
      el("span", { class: "ko-chart-mon" },
        monSprite(row.species, row.mon?.status),
        el("span", { class: "ko-chart-name" },
          el("span", { class: "mon-name" }, row.species),
          el("span", { class: "mon-route" }, row.mon ? routeName(row.mon.route_id) : "no longer in box"))),
      el("span", { class: "ko-chart-track" },
        el("span", { class: "ko-chart-bar-line" },
          el("span", { class: "ko-chart-bar", style: `--share: ${row.kos / most}` }),
          el("strong", { class: "ko-chart-count" }, String(row.kos))),
        el("span", { class: "ko-chart-battles" }, battles.join(" · "))));
  }));
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
    state.evolutions = game.evolutions;
    state.natures = game.natures;
    state.statuses = game.statuses;
    state.ivStats = game.iv_stats;
    for (const [id, names] of [["dl-moves", game.suggestions.moves], ["dl-abilities", game.suggestions.abilities],
      ["dl-items", game.suggestions.items]]) {
      $(`#${id}`).replaceChildren(...names.map((name) => el("option", { value: name })));
    }

    for (const btn of document.querySelectorAll(".tabs button")) {
      btn.addEventListener("click", () => showTab(btn.dataset.tab));
    }
    showTab(["encounters", "box", "fights", "kos", "notes"].includes(storageGet("tab")) ? storageGet("tab") : "encounters");

    $("#drawer-open").addEventListener("click", () =>
      setDrawer($("#tab-fights").classList.contains("drawer-closed")));
    $("#drawer-close").addEventListener("click", () => setDrawer(false));
    $("#drawer-scrim").addEventListener("click", () => setDrawer(false));
    $("#battle-filter").addEventListener("input", renderBattleList);
    $("#picker-remove").addEventListener("click", () => {
      $("#catch-picker").close();
      removeCatch(pickerRoute).catch(() => {});
    });
    // Clicking the dimmed backdrop (outside .picker-inner) closes a popup.
    for (const dialog of document.querySelectorAll("dialog.picker")) {
      dialog.addEventListener("click", (e) => {
        if (e.target === e.currentTarget) e.currentTarget.close();
      });
    }
    document.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && mobileLayout.matches) setDrawer(false);
    });
    for (const btn of document.querySelectorAll(".result-toggle button")) {
      btn.addEventListener("click", () => toggleResult(btn.dataset.result));
    }
    // Dropping a team member back on the box removes it from the team.
    makeDropTarget($("#box-panel"), (drag) => setSlot(drag.fromSlot, null),
      (drag) => drag.fromSlot !== null);
    setupKoBoard();

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
