"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------

const state = {
  routes: [],            // [{id, name, options: [{method, pokemon, rate, levels}]}]
  battles: [],           // [{id, name, location, level_cap, group_id, tags}] in game order
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
  fights: new Map(),     // battle_id -> {id, battle_id, result, members: [copy + {id, slot, catch_id}]}
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

  const headSprite = el("span", { class: "editor-sprite" }, sprite(species));
  const headName = el("h3", { class: "editor-species" }, species);
  const evolve = el("button", { type: "button", class: "evolve-button" }, "Evolve…");
  const refreshHead = () => {
    headSprite.replaceChildren(sprite(species));
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
    }, ...monLabel(mon), statusBadge(mon.status));
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
  return [sprite(mon.species),
    el("span", { class: "mon-name" }, mon.species),
    el("span", { class: "mon-route" }, [mon.level && `Lv ${mon.level}`, mon.routeName].filter(Boolean).join(" · "))];
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

function teamSlot(index, member) {
  const slot = el("div", { class: `team-slot${member ? " filled" : ""}` });
  if (member) {
    const source = member.catch_id === null ? null : catchById(member.catch_id);
    const remove = el("button", { type: "button", class: "remove", "aria-label": `Remove ${member.species} from the team` }, "×");
    remove.addEventListener("click", () => setSlot(index, null));
    slot.append(
      sprite(member.species),
      el("span", { class: "mon-name" }, member.species),
      el("span", { class: "mon-route" },
        [member.level && `Lv ${member.level}`, source ? routeName(source.route_id) : "no longer in box"]
          .filter(Boolean).join(" · ")),
      statusBadge(member.status),
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
  }, ...monLabel(mon), statusBadge(mon.status));
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

function toggleResult(result) {
  const current = state.fights.get(state.battleId)?.result ?? null;
  saveFight(currentSlots(), current === result ? null : result);
}

/** Apply a fight change immediately, then save it in the background. */
function saveFight(slots, result) {
  const attemptId = state.attempt.id;
  const battleId = state.battleId;
  const members = slots.flatMap((m, i) => (m ? [{ ...m, slot: i + 1 }] : []));
  // Saved copies are kept by id; new ones are copied from their box Pokemon.
  const payload = slots.map((m) => (m ? (m.id ? { id: m.id } : { catch_id: m.catch_id }) : null));
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
        api("PUT", `/attempts/${attemptId}/fights/${battleId}`, { members: payload, result }));
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
      renderBox();
      renderFightView();
    }
  });
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
    showTab(["encounters", "box", "fights", "notes"].includes(storageGet("tab")) ? storageGet("tab") : "encounters");

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
