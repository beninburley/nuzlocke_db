"use strict";

// The admin page (role "admin" only): Games, Roles, Trainer battles, Routing and
// Verification requests, picked by the URL's #hash. Trainer battles and Routing work on
// one game at a time (GAME, from site.js), picked on those pages once there are two. It uses app.js's helpers (api, el,
// sprite, enemySlot, trainerLabels, save...) without booting the tracker, so
// enemy teams look exactly as they do on the Trainer battles tab.

const admin = {
  me: null,            // the logged-in admin
  users: [],
  roles: [],
  natures: [],
  gameLoaded: false,
  battleId: null,      // battle shown on Trainer battles
  detail: null,        // its trainers and teams
  trainerIndex: 0,
  editing: null,       // trainer whose team is open in the editor
  routing: [],         // [{id, name, area, unlock, default_unlock, edited}] in game order
  splits: [],          // [{name, level_cap}] in game order
  games: [],           // [{slug, name, source, routes, battles, attempts}]
};

const ADMIN_VIEWS = ["games", "roles", "battles", "routing", "verification"];

async function adminBoot() {
  try {
    admin.me = (await api("GET", "/me")).user;
    setupAccountMenu(admin.me);  // site.js
    window.addEventListener("hashchange", () => showAdminView().catch(showError));
    $("#user-filter").addEventListener("input", renderUsers);
    $("#admin-battle-filter").addEventListener("input", renderAdminBattleList);
    $("#routing-filter").addEventListener("input", renderRouting);
    $("#team-form").addEventListener("submit", (e) => saveTeam(e).catch(() => {}));
    $("#game-form").addEventListener("submit", (e) => addGame(e).catch(showError));
    setupSlugField();
    for (const select of document.querySelectorAll(".admin-game-select")) {
      select.addEventListener("change", () => switchAdminGame(select.value).catch(showError));
    }
    await loadAdminGames();
    for (const btn of document.querySelectorAll(".team-close")) {
      btn.addEventListener("click", () => $("#team-editor").close());
    }
    await showAdminView();
  } catch (err) {
    showError(err);
  }
}

function showError(err) {
  setStatus(`Error: ${err.message}`, "error");
}

async function showAdminView() {
  const hash = location.hash.slice(1);
  const view = ADMIN_VIEWS.includes(hash) ? hash : "home";
  for (const name of ["home", ...ADMIN_VIEWS]) $(`#admin-${name}`).hidden = name !== view;
  if (view === "games") renderGames();
  if (view === "roles") await loadUsers();
  if (view === "battles") await loadAdminBattles();
  if (view === "routing") await loadRouting();
}

// --- Games ---------------------------------------------------------------------

async function loadAdminGames() {
  admin.games = (await api("GET", "/admin/games")).games;
  // The game Trainer battles and Routing show: the last one picked, if it's still here.
  const saved = storageGet("adminGame");
  if (admin.games.some((g) => g.slug === saved)) GAME.slug = saved;
  else if (!admin.games.some((g) => g.slug === GAME.slug)) GAME.slug = admin.games[0]?.slug ?? GAME.slug;
  for (const select of document.querySelectorAll(".admin-game-select")) {
    select.replaceChildren(...admin.games.map((g) => el("option", { value: g.slug }, g.name)));
    select.value = GAME.slug;
    select.closest(".admin-game-pick").hidden = admin.games.length < 2;
  }
}

/** Trainer battles and Routing switch to another game's data. */
async function switchAdminGame(slug) {
  GAME.slug = slug;
  storageSet("adminGame", slug);
  for (const select of document.querySelectorAll(".admin-game-select")) select.value = slug;
  Object.assign(admin, { gameLoaded: false, battleId: null, detail: null });
  battleDetails.clear();
  $("#admin-battle").replaceChildren(el("p", { class: "hint" }, "Pick a battle to see its enemy team."));
  await showAdminView();
}

function renderGames() {
  $("#games-count").textContent = `(${admin.games.length})`;
  $("#games-body").replaceChildren(...admin.games.map((g) => el("tr", {},
    el("td", {}, el("a", { href: `/${g.slug}/tracker` }, g.name)),
    el("td", { class: "muted" }, `/${g.slug}/`),
    el("td", { class: "num" }, String(g.routes)),
    el("td", { class: "num" }, String(g.battles)),
    el("td", { class: "num" }, String(g.attempts)),
    el("td", {}, g.source === "folder" ? "Repository" : "Added here"))));
}

const slugify = (name) => name.normalize("NFKD").replace(/[\u0300-\u036f]/g, "").toLowerCase()
  .replace(/&/g, " and ").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40).replace(/-+$/, "");

/** The address follows the name until it's edited by hand. */
function setupSlugField() {
  const form = $("#game-form");
  const { name, slug } = form.elements;
  let typed = false;
  const hint = () => {
    $("#game-slug-hint").textContent =
      `Its pages will be at /${slug.value || "emerald-kaizo"}/tracker. Lowercase letters, digits and hyphens.`;
  };
  name.addEventListener("input", () => {
    if (!typed) slug.value = slugify(name.value);
    hint();
  });
  slug.addEventListener("input", () => {
    typed = slug.value !== "";
    hint();
  });
}

async function addGame(e) {
  e.preventDefault();
  const form = $("#game-form");
  const { name, slug, file } = form.elements;
  const problems = $("#game-problems");
  formError(form, "");  // site.js
  problems.hidden = true;
  $("#game-done").hidden = true;
  if (!name.value.trim() || !slug.value || !file.files.length) {
    return formError(form, "Give the game a name and an address, and choose its game data file.");
  }
  const existing = admin.games.find((g) => g.slug === slug.value);
  if (existing?.source === "folder") {
    return formError(form, `${existing.name} uses the address /${existing.slug}/ and comes from the repository. Pick another address.`);
  }
  if (existing && !confirm(`Replace ${existing.name}'s game data? Its ${existing.attempts} attempt(s) stay.`)) return;
  let data;
  try {
    data = JSON.parse(await file.files[0].text());
  } catch (err) {
    return formError(form, `That file isn't valid JSON: ${err.message}`);
  }
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  setStatus("Adding the game…");
  try {
    const result = await apiCall("POST", "/admin/games", { name: name.value.trim(), slug: slug.value, data });
    if (!result.ok) {
      setStatus("");
      formError(form, result.data?.error ?? `Something went wrong (${result.status}).`);
      const list = result.data?.problems ?? [];
      problems.replaceChildren(...list.map((text) => el("li", {}, text)));
      problems.hidden = !list.length;
      return;
    }
    const { game, replaced } = result.data;
    setStatus(replaced ? "Replaced" : "Added", "ok");
    $("#game-done").textContent = `${replaced ? "Replaced" : "Added"} ${game.name}: ${game.routes} routes and ${game.battles} battles, at /${game.slug}/tracker.`;
    $("#game-done").hidden = false;
    form.reset();
    $("#game-slug-hint").textContent = "Its pages will be at /emerald-kaizo/tracker. Lowercase letters, digits and hyphens.";
    await loadAdminGames();
    renderGames();
  } finally {
    button.disabled = false;
  }
}

// --- Roles ---------------------------------------------------------------------

async function loadUsers() {
  const { users, roles } = await api("GET", "/admin/users");
  Object.assign(admin, { users, roles });
  $("#users-count").textContent = `(${users.length} account${users.length === 1 ? "" : "s"})`;
  renderUsers();
}

function renderUsers() {
  const query = $("#user-filter").value.trim().toLowerCase();
  $("#users-body").replaceChildren(...admin.users
    .filter((u) => u.username.toLowerCase().includes(query))
    .map(userRow));
}

/** One account: its role is a drop-down that saves on change (except your own). */
function userRow(user) {
  const isMe = user.username.toLowerCase() === admin.me.username.toLowerCase();
  const role = el("select", { "aria-label": `Role for ${user.username}`, disabled: isMe },
    ...admin.roles.map((r) => el("option", { value: r }, ROLE_LABELS[r] ?? r)));
  role.value = user.role;
  role.addEventListener("change", async () => {
    try {
      const { user: saved } = await save(() => api("PATCH", `/admin/users/${user.id}`, { role: role.value }));
      Object.assign(user, saved);
    } catch {
      role.value = user.role;  // save() already showed the error
    }
  });
  return el("tr", {},
    el("td", {}, user.username, isMe ? el("span", { class: "muted" }, " (you)") : ""),
    el("td", {}, role),
    el("td", {}, formatDate(user.created_at)),
    el("td", { class: "num" }, String(user.attempts)));
}

// --- Routing ---------------------------------------------------------------------

async function loadRouting() {
  const { routes, splits } = await api("GET", forGame("/admin/routing"));
  Object.assign(admin, { routing: routes, splits });
  renderRouting();
}

/** "After Leader Brawly (Lv 21)", or "From the start". */
function unlockLabel(split) {
  if (split === null) return "From the start";
  return `After ${split} (Lv ${admin.splits.find((s) => s.name === split)?.level_cap ?? "?"})`;
}

const routingChanged = (route) =>
  route.edited ? `By ${route.edited.by ?? "a deleted account"} on ${formatDate(route.edited.at)}` : "";

function renderRouting() {
  const query = $("#routing-filter").value.trim().toLowerCase();
  const changed = admin.routing.filter((r) => r.edited).length;
  $("#routing-changed").textContent = changed ? `(${changed} changed from the defaults)` : "";
  $("#routing-body").replaceChildren(...admin.routing
    .filter((r) => `${r.name} ${r.area ?? ""}`.toLowerCase().includes(query))
    .map(routingRow));
}

/** One route: when it opens is a drop-down that saves on change. */
function routingRow(route) {
  const choices = [null, ...admin.splits.map((s) => s.name)];
  const select = el("select", { "aria-label": `When ${route.name} opens up` },
    ...choices.map((split, i) => el("option", { value: String(i) },
      unlockLabel(split) + (split === route.default_unlock ? " · default" : ""))));
  select.value = String(choices.indexOf(route.unlock));
  const changedCell = el("td", { class: "muted" }, routingChanged(route));
  select.addEventListener("change", async () => {
    try {
      const { route: saved } = await save(() => api("PUT", `/admin/routing/${route.id}`, { unlock: choices[Number(select.value)] }));
      Object.assign(route, saved);
      changedCell.textContent = routingChanged(route);
      const count = admin.routing.filter((r) => r.edited).length;
      $("#routing-changed").textContent = count ? `(${count} changed from the defaults)` : "";
    } catch {
      select.value = String(choices.indexOf(route.unlock));  // save() already showed the error
    }
  });
  return el("tr", {},
    el("td", {}, route.name), el("td", {}, route.area ?? ""), el("td", {}, select), changedCell);
}

// --- Trainer battles ------------------------------------------------------------

async function loadAdminBattles() {
  if (!admin.gameLoaded) {
    const game = await api("GET", forGame("/game"));
    state.sprites = game.sprites;  // app.js's sprite() reads these
    state.battles = game.battles;
    admin.natures = game.natures;
    const lists = [["dl-species", Object.keys(game.sprites).sort()], ["dl-moves", game.suggestions.moves],
      ["dl-abilities", game.suggestions.abilities], ["dl-items", game.suggestions.items]];
    for (const [id, names] of lists) $(`#${id}`).replaceChildren(...names.map((n) => el("option", { value: n })));
    admin.gameLoaded = true;
  }
  renderAdminBattleList();
}

/** Every battle, grouped by split like the Trainer battles drawer. */
function renderAdminBattleList() {
  const query = $("#admin-battle-filter").value.trim().toLowerCase();
  const matches = (b) => !query || `${b.name} ${b.location ?? ""}`.toLowerCase().includes(query);
  $("#admin-battle-list").replaceChildren(...splitEnds().map((end) => {
    const battles = [...state.battles.filter((b) => b.group_id === end.id), end].filter(matches);
    if (!battles.length) return null;
    return el("li", { class: "admin-split" },
      el("h3", {}, `${end.split} Split`, el("span", { class: "muted" }, ` · level cap ${end.level_cap}`)),
      el("ol", { class: "trainer-list" }, ...battles.map((b) => {
        const button = el("button", {
          type: "button",
          class: b.level_cap !== null ? "boss-item" : "trainer-item",
          "aria-current": b.id === admin.battleId ? "true" : undefined,
        }, el("span", { class: "battle-status" }), el("span", { class: "battle-name" }, b.name),
        el("span", { class: "battle-meta" }, b.location ?? ""));
        button.addEventListener("click", () => selectAdminBattle(b.id).catch(showError));
        return el("li", {}, button);
      })));
  }).filter(Boolean));
}

async function selectAdminBattle(id, trainerIndex = 0) {
  admin.battleId = id;
  renderAdminBattleList();
  $("#admin-battle").replaceChildren(el("p", { class: "hint" }, "Loading…"));
  const detail = await api("GET", `/battles/${id}`);
  if (admin.battleId !== id) return;
  battleDetails.set(id, detail);  // keep app.js's cache in step with any edit
  Object.assign(admin, { detail, trainerIndex: Math.min(trainerIndex, detail.trainers.length - 1) });
  renderAdminBattle();
}

/** The battle's enemy team as a row of six, as on the Trainer battles tab, with Edit. */
function renderAdminBattle() {
  const battle = battleById(admin.battleId);
  const { trainers } = admin.detail;
  const trainer = trainers[admin.trainerIndex];
  const labels = trainerLabels(trainers);
  const edit = el("button", { type: "button", class: "primary" }, "Edit");
  edit.addEventListener("click", () => openTeamEditor(trainer));
  const copy = el("button", { type: "button" }, "Copy as Showdown");
  copy.addEventListener("click", () => copyShowdown(trainer.pokemon));
  const revert = el("button", { type: "button" }, "Revert to the spreadsheet's team");
  revert.addEventListener("click", () => revertTeam(trainer).catch(() => {}));
  $("#admin-battle").replaceChildren(
    el("div", { class: "admin-battle-head" },
      el("div", {},
        el("h3", {}, battle.name),
        el("span", { class: "muted" },
          [battle.location, battle.level_cap !== null && `Level cap ${battle.level_cap}`].filter(Boolean).join(" · "))),
      el("div", { class: "admin-battle-actions" }, copy, edit)),
    trainers.length > 1 ? el("div", { class: "trainer-tabs", role: "group", "aria-label": "Trainer" },
      ...trainers.map((t, i) => {
        const tab = el("button", { type: "button", "aria-pressed": String(i === admin.trainerIndex), title: t.name }, labels[i]);
        tab.addEventListener("click", () => {
          admin.trainerIndex = i;
          renderAdminBattle();
        });
        return tab;
      })) : "",
    el("p", { class: "hint" }, trainer.tags.includes("Tag Partner")
      ? `${trainer.name}: fights on the player's side in this tag battle.` : trainer.name),
    trainer.edited
      ? el("p", { class: "changed-banner admin-edited" },
        `Corrected by ${trainer.edited.by ?? "a deleted account"} on ${formatDate(trainer.edited.at)}. `, revert)
      : "",
    el("div", { class: "enemy-slots" }, ...Array.from({ length: TEAM_SIZE }, (_, i) => enemySlot(trainer.pokemon[i]))));
}

// --- the team editor (popup) -----------------------------------------------------

function openTeamEditor(trainer) {
  admin.editing = trainer;
  $("#team-title").textContent = `Edit ${trainer.name}'s team`;
  $("#team-slots").replaceChildren(...Array.from({ length: TEAM_SIZE }, (_, i) => slotEditor(i, trainer.pokemon[i])));
  formError($("#team-form"), "");
  $("#team-editor").showModal();
}

/** One enemy Pokémon's fields, laid out like its card: species, level/nature, item/ability, 2x2 moves. */
function slotEditor(index, mon) {
  const text = (name, value, list, placeholder) =>
    el("input", { name, value: value ?? "", list, placeholder, maxlength: "40", autocomplete: "off" });
  const field = (label, input) => el("label", { class: "field" }, el("span", { class: "field-label" }, label), input);
  const species = text("species", mon?.species, "dl-species", "Empty slot");
  const preview = el("span", { class: "slot-sprite" }, mon ? sprite(mon.species) : "");
  species.addEventListener("input", () =>
    preview.replaceChildren(state.sprites[species.value] ? sprite(species.value) : ""));
  const level = el("input", { name: "level", type: "number", min: "1", max: "100", step: "1", value: mon?.level ?? "" });
  const nature = el("select", { name: "nature" }, el("option", { value: "" }, "—"),
    ...admin.natures.map((n) => el("option", { value: n }, n)));
  nature.value = mon?.nature ?? "";
  return el("fieldset", { class: "slot-editor" },
    el("legend", {}, `Slot ${index + 1}`),
    el("div", { class: "slot-head" }, preview, field("Species", species)),
    el("div", { class: "editor-row" }, field("Level", level), field("Nature", nature)),
    el("div", { class: "editor-row" },
      field("Held item", text("item", mon?.item, "dl-items", "None")),
      field("Ability", text("ability", mon?.ability, "dl-abilities", "Ability"))),
    el("div", { class: "field" }, el("span", { class: "field-label" }, "Moves"),
      el("div", { class: "moves-grid" },
        ...[0, 1, 2, 3].map((i) => text(`move${i}`, mon?.moves[i], "dl-moves", `Move ${i + 1}`)))));
}

async function saveTeam(e) {
  e.preventDefault();  // only fires once the inputs pass their own checks
  const form = $("#team-form");
  // Blank slots are dropped, and the rest close up.
  const team = [...form.querySelectorAll(".slot-editor")].map((slot) => {
    const value = (name) => slot.querySelector(`[name="${name}"]`).value.trim();
    return {
      species: value("species"),
      level: value("level") ? Number(value("level")) : null,
      item: value("item") || null,
      ability: value("ability") || null,
      nature: value("nature") || null,
      moves: [0, 1, 2, 3].map((i) => value(`move${i}`) || null),
    };
  }).filter((mon) => mon.species);
  if (!team.length) return formError(form, "A trainer needs at least one Pokémon.");
  try {
    await save(() => api("PUT", forGame("/admin/trainer-team"), { trainer: admin.editing.key, pokemon: team }));
  } catch (err) {
    return formError(form, err.message);
  }
  $("#team-editor").close();
  await selectAdminBattle(admin.battleId, admin.trainerIndex);
}

async function revertTeam(trainer) {
  if (!confirm(`Put ${trainer.name}'s team back to the spreadsheet's? The corrections are lost.`)) return;
  await save(() => api("POST", forGame("/admin/trainer-team/revert"), { trainer: trainer.key }));
  await selectAdminBattle(admin.battleId, admin.trainerIndex);
}

if (document.body.dataset.page === "admin") adminBoot();
