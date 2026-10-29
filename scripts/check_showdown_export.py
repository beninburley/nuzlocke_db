"""Check that the Showdown export (static/showdown.js) reads back through "Update from script".

Formats every species in the game data, and every trainer's team, with the export (run under
Node), then parses the paste with box_script.py: each set has to parse with no problems or
skipped lines, give back the same details, and update that very species (not evolve it).

Usage:
    python scripts/check_showdown_export.py      # needs node on the PATH
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import box_script  # noqa: E402

GAME_DATA = ROOT / "data" / "game_data.json"
EVOLUTIONS = ROOT / "data" / "evolutions.json"
STATS = ["hp", "atk", "def", "spa", "spd", "spe"]
NODE = """
const { showdownText } = require(process.argv[1]);
let input = "";
process.stdin.on("data", (chunk) => { input += chunk; });
process.stdin.on("end", () => process.stdout.write(showdownText(JSON.parse(input))));
"""


def export(mons):
    out = subprocess.run(["node", "-e", NODE, str(ROOT / "static" / "showdown.js")], input=json.dumps(mons),
                         capture_output=True, text=True, encoding="utf-8", check=True)
    return out.stdout


def box_mons(data):
    """One made-up box Pokémon per species, with a spread of known, unknown and non-31 IVs."""
    species = {e["pokemon"] for r in data["routes"] for e in r["encounters"]}
    species |= {s for family in data["families"] for s in family}
    mons = []
    for i, name in enumerate(sorted(species)):
        ivs = {stat: [None, 31, 0, 4 + j][(i + j) % 4] for j, stat in enumerate(STATS)}
        mons.append({"species": name, "level": i % 100 + 1, "ability": "Intimidate" if i % 3 else None,
                     "nature": "Hasty" if i % 2 else None, "item": "Lum Berry" if i % 5 else None,
                     "moves": ["Tackle", None, "Ice Beam", "Will-O-Wisp"][: i % 5], "ivs": ivs})
    return mons


def check(mons, label, lines, families):
    sets = box_script.parse(export(mons))
    failures = []
    if len(sets) != len(mons):
        return [f"{label}: exported {len(mons)} Pokémon but read back {len(sets)} sets"]
    for mon, s in zip(mons, sets):
        want = {"level": mon["level"], "ability": mon["ability"], "nature": mon["nature"], "item": mon["item"],
                "moves": [m for m in mon["moves"] if m]}
        got = {key: s.details.get(key) for key in want}
        got["moves"] = s.details.get("moves", [])
        if mon.get("ivs") and any(v not in (None, 31) for v in mon["ivs"].values()):
            want["ivs"] = {stat: 31 if v is None else v for stat, v in mon["ivs"].items()}
            got["ivs"] = s.details.get("ivs")
        if s.problem or s.ignored:
            failures.append(f"{label}: {mon['species']} -> {s.problem or s.ignored}")
        elif got != want:
            failures.append(f"{label}: {mon['species']} read back as {got}, not {want}")
        else:  # the set has to update this Pokémon, as it would in your box
            box = [{"id": 1, "pokemon": mon["species"], "species": mon["species"], "route": "Route"}]
            _, species, problem = box_script.match(s.name, box, lines, families)
            if species != mon["species"]:
                failures.append(f"{label}: {s.name!r} would update {mon['species']!r} as {species!r} ({problem})")
    return failures


def main():
    data = json.loads(GAME_DATA.read_text(encoding="utf-8"))
    lines = {k: tuple(v) for k, v in json.loads(EVOLUTIONS.read_text(encoding="utf-8")).items()}
    families = {s: i for i, family in enumerate(data["families"]) for s in family}
    box = box_mons(data)
    enemies = [p for b in data["battles"] for t in b["trainers"] for p in t["pokemon"]]
    failures = check(box, "box", lines, families) + check(enemies, "trainers", lines, families)
    for failure in failures:
        print(failure)
    print(f"Checked {len(box)} species and {len(enemies)} trainer Pokémon: "
          + (f"{len(failures)} failed" if failures else "all read back"))
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
