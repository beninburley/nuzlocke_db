"use strict";

// Light or dark theme. Loaded in <head> so the saved choice applies before the
// page paints; with no choice saved, the system setting decides (tokens.css).
// The #theme-toggle button in the top bar flips it and remembers the choice.

(() => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  } catch { /* storage blocked: follow the system */ }

  const current = () => root.dataset.theme ?? (dark.matches ? "dark" : "light");

  document.addEventListener("DOMContentLoaded", () => {
    const button = document.querySelector("#theme-toggle");
    if (!button) return;
    const label = () => {
      const isDark = current() === "dark";
      button.setAttribute("aria-pressed", String(isDark));
      button.title = isDark ? "Switch to light theme" : "Switch to dark theme";
    };
    button.addEventListener("click", () => {
      root.dataset.theme = current() === "dark" ? "light" : "dark";
      try { localStorage.setItem("theme", root.dataset.theme); } catch { /* not remembered */ }
      label();
    });
    dark.addEventListener("change", label);
    label();
  });
})();
