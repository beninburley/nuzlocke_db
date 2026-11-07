"use strict";

// Light or dark theme. Loaded in <head> so the saved choice applies before the
// page paints; with no choice saved, the system setting decides (tokens.css).
// The site bar's toggles (#theme-toggle, and the phone menu's [data-theme-toggle] row)
// flip it and remember the choice.

(() => {
  const root = document.documentElement;
  const dark = matchMedia("(prefers-color-scheme: dark)");
  try {
    const saved = localStorage.getItem("theme");
    if (saved === "light" || saved === "dark") root.dataset.theme = saved;
  } catch { /* storage blocked: follow the system */ }

  const current = () => root.dataset.theme ?? (dark.matches ? "dark" : "light");

  document.addEventListener("DOMContentLoaded", () => {
    const buttons = document.querySelectorAll("#theme-toggle, [data-theme-toggle]");
    if (!buttons.length) return;
    const label = () => {
      const isDark = current() === "dark";
      for (const button of buttons) button.setAttribute("aria-pressed", String(isDark));
      document.querySelector("#theme-toggle")?.setAttribute("title", isDark ? "Switch to light theme" : "Switch to dark theme");
    };
    for (const button of buttons) {
      button.addEventListener("click", () => {
        root.dataset.theme = current() === "dark" ? "light" : "dark";
        try { localStorage.setItem("theme", root.dataset.theme); } catch { /* not remembered */ }
        label();
      });
    }
    dark.addEventListener("change", label);
    label();
  });
})();
