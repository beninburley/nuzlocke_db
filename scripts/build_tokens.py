"""Turn the design system's tokens into CSS custom properties.

Reads design-system/tokens.json and writes static/tokens.css: the Plus Jakarta
Sans @font-face rules, every token as a --custom-property on :root (the light
theme), and the dark theme under [data-theme="dark"] and, when no theme is
chosen, prefers-color-scheme: dark. style.css only uses these variables, so
re-run this after changing tokens.json.

Type styles become font shorthands, used as `font: var(--text-body)`, with
`--text-<name>-tracking` beside the ones that set letter-spacing.

Usage:
    python scripts/build_tokens.py
"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ROOT / "design-system" / "tokens.json"
OUT = ROOT / "static" / "tokens.css"
FONT_URL = "/design-system/fonts/"  # served by app.py from design-system/fonts


def themed(tokens, prefix=""):
    """[(name, light, dark)] for tokens whose value differs per theme, plus [(name, value)] for the rest."""
    split, fixed = [], []
    for t in tokens:
        if isinstance(t["value"], dict):
            split.append((prefix + t["name"], t["value"]["light"], t["value"]["dark"]))
        else:
            fixed.append((prefix + t["name"], t["value"]))
    return split, fixed


def main():
    data = json.loads(TOKENS.read_text(encoding="utf-8"))
    colors, fixed_colors = themed(data["color"]["tokens"])
    shadows, _ = themed(data["shadow"]["tokens"])

    out = ["/* Generated from design-system/tokens.json by scripts/build_tokens.py. Don't edit by hand. */", ""]
    for font in data["type"]["fonts"]:
        out += [
            "@font-face {",
            f'  font-family: "{font["family"]}";',
            f'  src: url("{FONT_URL}{Path(font["file"]).name}") format("woff2");',
            f'  font-weight: {font["weight"]};',
            f'  font-style: {font["style"]};',
            "  font-display: swap;",
            "}",
        ]

    out += ["", ":root {", "  color-scheme: light;"]
    out += [f"  --{name}: {light};" for name, light, _ in colors]
    out += [f"  --{name}: {value};" for name, value in fixed_colors]
    out += [f"  --{name}: {light};" for name, light, _ in shadows]
    out.append("")
    for family, stack in data["type"]["families"].items():
        out.append(f"  --font-{family}: {stack};")
    for group in data["type"]["groups"]:
        for s in group["styles"]:
            family = f'var(--font-{group["family"]})'
            out.append(f'  --text-{s["name"]}: {s["fontWeight"]} {s["fontSize"]}/{s["lineHeight"]} {family};')
            if "letterSpacing" in s:
                out.append(f'  --text-{s["name"]}-tracking: {s["letterSpacing"]};')
    out.append("")
    for section in ("spacing", "radius", "size", "breakpoint"):
        out += [f'  --{t["name"]}: {t["value"]};' for t in data[section]["tokens"]]
    out += ["}", ""]

    dark = ["  color-scheme: dark;"]
    dark += [f"  --{name}: {d};" for name, _, d in colors]
    dark += [f"  --{name}: {d};" for name, _, d in shadows]
    out += ['[data-theme="dark"] {', *dark, "}", ""]
    out += ["@media (prefers-color-scheme: dark) {", '  :root:not([data-theme="light"]) {']
    out += ["  " + line for line in dark]
    out += ["  }", "}", ""]

    OUT.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
