"use strict";

// Shared by every page: calling the account API, the account menu in the top
// bar, and the landing, login and account pages (picked by <body data-page>).

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

/** The top-right account button: who's logged in, the account page and logging out. */
function setupAccountMenu(user) {
  const button = document.querySelector("#account-button");
  const menu = document.querySelector("#account-popover");
  if (!button || !user) return;
  document.querySelector("#account-name").textContent = user.username;
  document.querySelector("#account-username").textContent = user.username;
  document.querySelector("#account-role").textContent = ROLE_LABELS[user.role] ?? user.role;
  button.hidden = false;
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
  document.querySelector("#logout").addEventListener("click", logOut);
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
  if (!data?.user) return;
  // Already logged in: offer the tracker rather than logging in.
  document.querySelector("#landing-actions").replaceChildren(
    Object.assign(document.createElement("a"), { className: "button primary", href: "/app", textContent: "Open your tracker" }));
  document.querySelector("#hero-actions").replaceChildren(
    Object.assign(document.createElement("a"), { className: "button primary", href: "/app", textContent: "Open your tracker" }),
    Object.assign(document.createElement("a"), { className: "button", href: "/account", textContent: `Account (${data.user.username})` }));
}

// --- login / create account ------------------------------------------------------

function loginPage() {
  const params = new URLSearchParams(location.search);
  // Only ever send people on to this site's own pages.
  const next = ["/app", "/account"].includes(params.get("next")) ? params.get("next") : "/app";
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

const PAGES = { landing: landingPage, login: loginPage, account: accountPage };
PAGES[document.body.dataset.page]?.();
