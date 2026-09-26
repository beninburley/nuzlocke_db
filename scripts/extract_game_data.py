"""Extract game-specific data from the Run & Bun master sheet into data/game_data.json.

Game data = things that are the same for every attempt: the route list and each
route's encounter table (Encounters tab), the boss fights and their level caps
(header rows of the Past Boss Fights tab), and the dupes-clause evolution
families (helper table at the bottom of the Encounters tab).

Usage:
    python scripts/extract_game_data.py ["path/to/sheet.xlsx"]
"""
import json
import sys
from pathlib import Path

import openpyxl

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_XLSX = ROOT / "Copy of Run & Bun Master Sheet.xlsx"
OUT = ROOT / "data" / "game_data.json"

# --- Encounters tab layout -------------------------------------------------
HEADER_ROW = 2
SECTIONS = [  # (method, first row, last row)
    ("Land", 5, 16),
    ("Fishing", 17, 26),
    ("Surf", 27, 31),
    ("Rocks", 32, 36),
    ("Other", 37, 58),
]
STARTER_COL = 2       # Starter block: Level, Pokemon, checkbox
FIRST_ROUTE_COL = 5   # Every route block after it: %, Level, Pokemon, checkbox
ROUTE_BLOCK_WIDTH = 4
FAMILY_ROWS = range(94, 131)  # one evolution family per column
FAMILY_FIRST_COL = 3

# --- Past Boss Fights tab layout -------------------------------------------
BOSS_LEVEL_ROW = 1
BOSS_NAME_ROW = 2
BOSS_FIRST_COL = 2


def clean(value):
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


def normalize_rate(value):
    """'20%' -> 20.0, 0.0909 -> 9.09 (fractions are used for gift/fossil odds)."""
    value = clean(value)
    if value is None:
        return None
    if isinstance(value, str):
        return float(value.rstrip("%"))
    if isinstance(value, (int, float)):
        return round(value * 100, 2) if value <= 1 else float(value)
    return None


def normalize_level(value):
    value = clean(value)
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_block(ws, rate_col, level_col, pokemon_col, methods=None):
    encounters = []
    for method, first, last in SECTIONS:
        if methods and method not in methods:
            continue
        for row in range(first, last + 1):
            pokemon = clean(ws.cell(row, pokemon_col).value)
            if not isinstance(pokemon, str):
                continue
            encounters.append({
                "method": method,
                "pokemon": pokemon,
                "rate": normalize_rate(ws.cell(row, rate_col).value) if rate_col else None,
                "level": normalize_level(ws.cell(row, level_col).value),
            })
    return encounters


def extract_routes(ws):
    # The Starter column's upper rows hold rule-settings questions, not Pokemon.
    routes = [{
        "name": clean(ws.cell(HEADER_ROW, STARTER_COL).value),
        "encounters": read_block(ws, None, STARTER_COL, STARTER_COL + 1, methods={"Other"}),
    }]
    col = FIRST_ROUTE_COL
    while (name := clean(ws.cell(HEADER_ROW, col).value)) is not None:
        routes.append({"name": name, "encounters": read_block(ws, col, col + 1, col + 2)})
        col += ROUTE_BLOCK_WIDTH
    return routes


def extract_families(ws):
    families = []
    for col in range(FAMILY_FIRST_COL, ws.max_column + 1):
        members = [clean(ws.cell(row, col).value) for row in FAMILY_ROWS]
        members = [m for m in members if isinstance(m, str)]
        if members:
            families.append(members)
    return families


def extract_bosses(ws):
    bosses = []
    col = BOSS_FIRST_COL
    while (name := clean(ws.cell(BOSS_NAME_ROW, col).value)) is not None:
        level = clean(ws.cell(BOSS_LEVEL_ROW, col).value)
        level_cap = int(level.lower().replace("lvl", "").strip()) if isinstance(level, str) else None
        bosses.append({"name": name, "level_cap": level_cap})
        col += 1
    return bosses


def main():
    xlsx = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_XLSX
    wb = openpyxl.load_workbook(xlsx, data_only=True)
    data = {
        "source": xlsx.name,
        "routes": extract_routes(wb["Encounters"]),
        "bosses": extract_bosses(wb["Past Boss Fights"]),
        "families": extract_families(wb["Encounters"]),
    }
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    n_enc = sum(len(r["encounters"]) for r in data["routes"])
    print(f"Wrote {OUT}: {len(data['routes'])} routes, {n_enc} encounter slots, "
          f"{len(data['bosses'])} bosses, {len(data['families'])} families")


if __name__ == "__main__":
    main()
