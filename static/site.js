"use strict";

// Shared by every page: calling the account API, the site bar (links, account
// menu, phone menu), and the landing, login, account and battles pages (picked by
// <body data-page>).

const ROLE_LABELS = { trainer: "Trainer", mod: "Mod", content_creator: "Content creator", admin: "Admin" };

/** fetch() for the JSON API -> {ok, status, data}. The server only accepts changes carrying X-Requested-With. */
async function apiCall(method, path, body) {
  const res = await fetch(`/api${path}`, {
    method,
    headers: { "X-Requested-With": "fetch", ...(body === undefined ? {} : { "Content-Type": "application/json" }) },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = res.status === 204 ? null : await res.json().catch(() => ({}));
  return { ok: res.ok, status: res.status, data };
}

async function logOut() {
  await apiCall("POST", "/logout");
  location.href = "/";
}

/** "2026-09-28 22:51:04" (UTC, from SQLite) -> a local date. */
function formatDate(sqliteTime) {
  const date = new Date(`${sqliteTime.replace(" ", "T")}Z`);
  return Number.isNaN(date.getTime()) ? sqliteTime : date.toLocaleDateString(undefined, { dateStyle: "long" });
}

// --- site bar (every page) ----------------------------------------------------------

// Games on the site, by the slug in their URLs. The game picker shows once there are two.
const GAMES = [{ slug: "run-and-bun", name: "Run & Bun" }];
const GAME = GAMES.find((game) => location.pathname.startsWith(`/${game.slug}/`)) ?? GAMES[0];
const gamePath = (page) => `/${GAME.slug}/${page}`;

const SVG = (paths) => `<svg class="icon" viewBox="0 0 24 24" aria-hidden="true">${paths}</svg>`;
const BAR_ICONS = {
  moon: SVG('<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>').replace('class="icon"', 'class="icon icon-moon"'),
  sun: SVG('<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.93 4.93l1.41 1.41M17.66 17.66l1.41 1.41M2 12h2M20 12h2M6.34 17.66l-1.41 1.41M19.07 4.93l-1.41 1.41"/>')
    .replace('class="icon"', 'class="icon icon-sun"'),
  menu: SVG('<path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/>').replace('class="icon"', 'class="icon icon-menu"'),
  close: SVG('<path d="M18 6 6 18"/><path d="m6 6 12 12"/>').replace('class="icon"', 'class="icon icon-close"'),
  chevron: SVG('<path d="m6 9 6 6 6-6"/>'),
};

/**
 * Fill <header id="site-bar">: the wordmark, the game picker, the site's links, the theme
 * toggle, then Log in or the account menu, and on phones a Menu button that holds them all.
 * The header's data-current names the page's own link; data-status adds a save-status line.
 * Signed-in and signed-out parts stay hidden until showSignedIn() or showSignedOut().
 */
function buildSiteBar() {
  const bar = document.querySelector("#site-bar");
  if (!bar) return;
  const link = (page, href, label, extra = "") =>
    `<a class="site-link" href="${href}"${bar.dataset.current === page ? ' aria-current="page"' : ""} ${extra}>${label}</a>`;
  const links = () => link("tracker", gamePath("tracker"), "My runs", "data-signed-in hidden")
    + link("battles", gamePath("battles"), "Battles")
    + link("admin", "/admin", "Admin", "data-admin hidden");
  bar.innerHTML = `
    <a class="wordmark" href="/">Nuzhub</a>
    <button id="game-picker" class="game-picker" type="button" title="Switch game" hidden>${GAME.name} ${BAR_ICONS.chevron}</button>
    <nav class="site-links" aria-label="Site">${links()}</nav>
    <div class="site-end">
      ${bar.dataset.status === undefined ? "" : '<span id="status" role="status" aria-live="polite"></span>'}
      <button id="theme-toggle" class="theme-toggle" type="button" aria-label="Dark theme" aria-pressed="false">${BAR_ICONS.moon}${BAR_ICONS.sun}</button>
      <a class="button site-login" href="/login" data-signed-out hidden>Log in</a>
      <div class="account-menu" data-signed-in hidden>
        <button id="account-button" type="button" aria-haspopup="true" aria-expanded="false" aria-controls="account-popover">
          <span class="account-name"></span>${BAR_ICONS.chevron}
        </button>
        <div id="account-popover" class="account-popover" hidden>
          <p class="account-who"><strong class="account-name"></strong><span class="muted account-role"></span></p>
          <a href="/account">Account settings</a>
          <button type="button" data-logout>Log out</button>
        </div>
      </div>
      <button id="menu-button" class="menu-button" type="button" aria-expanded="false" aria-controls="site-menu" aria-label="Menu">
        ${BAR_ICONS.menu}${BAR_ICONS.close}
      </button>
    </div>
    <div id="site-menu" class="site-menu" hidden>
      <nav class="menu-links" aria-label="Site">${links()}</nav>
      <div class="menu-section">
        <p class="menu-who" data-signed-in hidden><strong class="account-name"></strong><span class="muted account-role"></span></p>
        <a class="menu-row" href="/account" data-signed-in hidden>Account settings</a>
        <button class="menu-row theme-toggle-row" type="button" data-theme-toggle aria-pressed="false">Dark theme<span class="switch" aria-hidden="true"></span></button>
        <button class="menu-row" type="button" data-logout data-signed-in hidden>Log out</button>
      </div>
    </div>`;
  bar.querySelector("#game-picker").hidden = GAMES.length < 2;
  setupPopover(bar.querySelector("#account-button"), bar.querySelector("#account-popover"));
  setupPopover(bar.querySelector("#menu-button"), bar.querySelector("#site-menu"));
  for (const button of bar.querySelectorAll("[data-logout]")) button.addEventListener("click", logOut);
}

/** A button that opens and closes a menu; outside clicks and Escape close it. */
function setupPopover(button, menu) {
  const setOpen = (open) => {
    menu.hidden = !open;
    button.setAttribute("aria-expanded", String(open));
  };
  button.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(menu.hidden);
  });
  document.addEventListener("click", (e) => {
    if (!menu.hidden && !menu.contains(e.target)) setOpen(false);
  });
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !menu.hidden) {
      setOpen(false);
      button.focus();
    }
  });
}

/** Show the signed-in parts of the site bar for `user`: My runs, Admin for admins, the account menu. */
function setupAccountMenu(user) {
  const bar = document.querySelector("#site-bar");
  if (!bar) return;
  if (!user) return showSignedOut();
  for (const node of bar.querySelectorAll("[data-signed-in]")) node.hidden = false;
  for (const node of bar.querySelectorAll("[data-signed-out]")) node.hidden = true;
  for (const node of bar.querySelectorAll("[data-admin]")) node.hidden = user.role !== "admin";
  for (const node of bar.querySelectorAll(".account-name")) node.textContent = user.username;
  for (const node of bar.querySelectorAll(".account-role")) node.textContent = ROLE_LABELS[user.role] ?? user.role;
  bar.querySelector(".wordmark").href = gamePath("tracker");
}

function showSignedOut() {
  const bar = document.querySelector("#site-bar");
  for (const node of bar?.querySelectorAll("[data-signed-out]") ?? []) node.hidden = false;
}

/** Show a form's error (or clear it with ""). */
function formError(form, message) {
  const error = form.querySelector(".form-error");
  error.textContent = message;
  error.hidden = !message;
}

/** Submit a form's fields as JSON; while it runs, its button is disabled. */
async function submitForm(form, method, path, body) {
  const button = form.querySelector("button[type=submit]");
  button.disabled = true;
  formError(form, "");
  try {
    const result = await apiCall(method, path, body);
    if (!result.ok) formError(form, result.data?.error ?? `Something went wrong (${result.status}).`);
    return result;
  } catch {
    formError(form, "Couldn't reach the server. Check your connection and try again.");
    return { ok: false };
  } finally {
    button.disabled = false;
  }
}

// --- landing page ------------------------------------------------------------

async function landingPage() {
  const { data } = await apiCall("GET", "/me");
  setupAccountMenu(data?.user);
  if (!data?.user) return;
  // Already logged in: offer the tracker rather than logging in.
  document.querySelector("#hero-actions").replaceChildren(
    Object.assign(document.createElement("a"), { className: "button primary", href: gamePath("tracker"), textContent: "Open your tracker" }),
    Object.assign(document.createElement("a"), { className: "button", href: "/account", textContent: `Account (${data.user.username})` }));
}

// --- login / create account ------------------------------------------------------

function loginPage() {
  const params = new URLSearchParams(location.search);
  // Only ever send people on to this site's own pages.
  const pages = [...GAMES.flatMap((game) => [`/${game.slug}/tracker`, `/${game.slug}/battles`]), "/account", "/admin"];
  const next = pages.includes(params.get("next")) ? params.get("next") : gamePath("tracker");
  const forms = { login: document.querySelector("#login-form"), signup: document.querySelector("#signup-form") };

  const showMode = (mode) => {
    for (const tab of document.querySelectorAll(".auth-tabs [data-mode]")) {
      tab.setAttribute("aria-selected", String(tab.dataset.mode === mode));
    }
    for (const [name, form] of Object.entries(forms)) form.hidden = name !== mode;
    forms[mode].querySelector("input").focus();
  };
  for (const tab of document.querySelectorAll(".auth-tabs [data-mode]")) {
    tab.addEventListener("click", () => showMode(tab.dataset.mode));
  }
  showMode(params.get("mode") === "signup" ? "signup" : "login");

  forms.login.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { username, password } = forms.login.elements;
    const { ok } = await submitForm(forms.login, "POST", "/login", { username: username.value, password: password.value });
    if (ok) location.href = next;
    else password.select();
  });
  forms.signup.addEventListener("submit", async (e) => {
    e.preventDefault();
    const { username, password, confirm } = forms.signup.elements;
    if (password.value !== confirm.value) return formError(forms.signup, "The passwords don't match.");
    const { ok } = await submitForm(forms.signup, "POST", "/signup", { username: username.value, password: password.value });
    if (ok) location.href = next;
  });
}

// --- account page ------------------------------------------------------------------

async function accountPage() {
  const { data } = await apiCall("GET", "/me");
  if (!data?.user) {
    location.href = "/login?next=/account";
    return;
  }
  const user = data.user;
  setupAccountMenu(user);
  document.querySelector("#acct-username").textContent = user.username;
  document.querySelector("#acct-role").textContent = ROLE_LABELS[user.role] ?? user.role;
  document.querySelector("#acct-created").textContent = formatDate(user.created_at);
  document.querySelector("#acct-attempts").textContent = String(user.attempts);

  const form = document.querySelector("#password-form");
  const done = document.querySelector("#password-done");
  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    done.hidden = true;
    const { current, password, confirm } = form.elements;
    if (password.value !== confirm.value) return formError(form, "The new passwords don't match.");
    const { ok } = await submitForm(form, "POST", "/me/password",
      { current_password: current.value, new_password: password.value });
    if (ok) {
      form.reset();
      done.hidden = false;
    }
  });
  document.querySelector("#logout-here").addEventListener("click", logOut);
  document.querySelector("#logout-everywhere").addEventListener("click", async () => {
    if (!confirm("Log out on every device, including this one?")) return;
    await apiCall("POST", "/me/logout-everywhere");
    location.href = "/";
  });
}

// --- battles (public; placeholders until Public battle search) ------------------------

async function battlesPage() {
  const id = /\/battles\/(\d+)$/.exec(location.pathname)?.[1];
  document.querySelector("#battles-search").hidden = Boolean(id);
  document.querySelector("#battle-guide").hidden = !id;
  const { data } = await apiCall("GET", "/me");
  setupAccountMenu(data?.user);
}

buildSiteBar();
const PAGES = { landing: landingPage, login: loginPage, account: accountPage, battles: battlesPage };
PAGES[document.body.dataset.page]?.();
