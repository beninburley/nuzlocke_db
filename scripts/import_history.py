"""Import past attempts from the master sheet into the database (best effort).

Reads the "Past Encounters" and "Past Boss Fights" tabs:
  * every attempt number becomes an attempt
  * every route cell becomes a catch if it matches that route's encounter table.
    Ability markers ("Lillipup-", "Tyrogue+") are stripped, and names are
    matched through evolution families, so "Hatterene" on Route 116 -> Hatenna
    and "Zigzagoon" on Route 101 -> Zigzagoon-G. "-" means no catch.
  * every boss column becomes a fight: "Win?" -> result, and each team name is
    matched to one of that attempt's catches through its evolution family
    ("Grotle" -> the Turtwig caught as the starter). Small typos are fixed.
    Boss fights against two separate trainers (the Museum grunts, Tate & Liza)
    are a battle per trainer; each gets the column's team and result.
  * free-text cells (how the run ended) and "Killed:" rows go to the notes.
Anything that can't be matched is skipped and listed in the report.

Usage:
    python scripts/import_history.py ["path/to/sheet.xlsx"] [--replace]

Attempts that already exist in the DB are skipped unless --replace is given,
which deletes and re-imports them.
"""
import difflib
import re
import sys
from collections import defaultdict
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402

DEFAULT_XLSX = db.ROOT / "Copy of Run & Bun Master Sheet.xlsx"

# Past Encounters layout: header row 5; Starter block is cols 2-4, then one
# 4-column block per route starting at col 5. Each attempt uses two rows:
# catches, then "Killed:" details.
ENC_HEADER_ROW = 5
ENC_STARTER_COL = 2
ENC_FIRST_ROUTE_COL = 5
ENC_BLOCK_WIDTH = 4

# Past Boss Fights layout: boss names in row 2 from col 2; each attempt is an
# "Attempt N" row plus five more team rows, followed by a "Win?" row.
BOSS_NAME_ROW = 2
BOSS_FIRST_COL = 2

NO_CATCH = {"", "-"}


def text(value):
    return value.strip() if isinstance(value, str) else ""


class Names:
    """Resolves hand-typed names to species from the game data."""

    def __init__(self, conn):
        self.family = {r["species"]: r["family_id"]
                       for r in conn.execute("SELECT species, family_id FROM species_families")}
        self.species = list(self.family)
        self.fixes = {}  # raw -> corrected, for the report

    def resolve(self, raw):
        """Return a species name for raw text, or None if it isn't a Pokemon."""
        name = raw.strip().rstrip("+-?").strip()
        if not name:
            return None
        if name in self.family:
            return name
        # Regional-only species typed without the suffix: Zigzagoon -> Zigzagoon-G
        forms = [s for s in self.species if s.split("-")[0].lower() == name.lower()]
        if forms:
            self.fixes[raw] = forms[0]
            return forms[0]
        close = difflib.get_close_matches(name, self.species, n=1, cutoff=0.8)
        if close:
            self.fixes[raw] = close[0]
            return close[0]
        return None

    def same_family(self, a, b):
        return a == b or (a in self.family and self.family.get(a) == self.family.get(b))


def pick(candidates, species, names):
    """Choose the candidate matching species exactly, else by evolution family."""
    exact = [c for c in candidates if c[1] == species]
    if exact:
        return exact[0]
    family = [c for c in candidates if names.same_family(c[1], species)]
    return family[0] if family else None


def match_team(cells, box, names):
    """One boss column's cells -> (members, unmatched, free text).

    members is [(catch_id, species used)] in slot order, matched to the box
    [(catch_id, caught species)] through evolution families, so "Grotle" is the
    Turtwig caught as the starter, used as a Grotle in that fight.
    """
    members, unmatched, free_text = [], [], []
    for cell in cells:
        if not cell:
            continue
        species = names.resolve(cell)
        if species is None:
            free_text.append(cell)
            continue
        used = {catch_id for catch_id, _ in members}
        match = pick([b for b in box if b[0] not in used], species, names)
        if match:
            members.append((match[0], species))
        else:
            unmatched.append(cell)
    return members[:6], unmatched, free_text


def read_encounters(ws, names, route_options, report):
    """-> {attempt: {"catches": {route: pokemon}, "deaths": [str]}}"""
    blocks = [(ENC_STARTER_COL, ENC_FIRST_ROUTE_COL)]
    blocks += [(c, c + ENC_BLOCK_WIDTH) for c in range(ENC_FIRST_ROUTE_COL, ws.max_column + 1, ENC_BLOCK_WIDTH)]
    blocks = [(text(ws.cell(ENC_HEADER_ROW, start).value), start, end) for start, end in blocks]
    blocks = [b for b in blocks if b[0]]

    attempts = {}
    for row in range(ENC_HEADER_ROW + 1, ws.max_row + 1):
        number = ws.cell(row, 1).value
        if not isinstance(number, (int, float)):
            continue
        number = int(number)
        catches, deaths = {}, []
        for route, start, end in blocks:
            raw = text(ws.cell(row, start).value)
            if raw not in NO_CATCH:
                species = names.resolve(raw)
                options = [(o, o) for o in route_options.get(route, ())]
                match = pick(options, species, names) if species else None
                if match:
                    catches[route] = match[0]
                else:
                    report["catch"].append(f"#{number} {route}: '{raw}' is not in the encounter table")
            # "Killed:" followed by trainer/Pokemon. A bare "Killed:" label is
            # template filler (attempt 101 has one in every column), not a death.
            killed = [text(ws.cell(row + 1, c).value) for c in range(start, end)]
            killed = [k for k in killed if k]
            marked = any(k.lower().startswith("kill") for k in killed)
            detail = " ".join(k for k in killed if not k.lower().startswith("kill"))
            if marked and detail:
                who = catches.get(route) or raw or "?"
                deaths.append(f"{who} ({route}): {detail}")
        attempts[number] = {"catches": catches, "deaths": deaths}
    return attempts


def read_boss_fights(ws, bosses):
    """-> {attempt: {"columns": {boss: [cell text x6]}, "won": {boss: bool}}}"""
    boss_cols = {}
    col = BOSS_FIRST_COL
    while text(ws.cell(BOSS_NAME_ROW, col).value):
        boss_cols[col] = text(ws.cell(BOSS_NAME_ROW, col).value)
        col += 1
    unknown = set(boss_cols.values()) - set(bosses)
    if unknown:
        raise SystemExit(f"Bosses missing from game data: {unknown}")

    attempts = {}
    row = 1
    while row <= ws.max_row:
        m = re.fullmatch(r"attempt\s*(\d+)", text(ws.cell(row, 1).value), re.I)
        if not m:
            row += 1
            continue
        team_rows = []
        while row <= ws.max_row and text(ws.cell(row, 1).value).lower() != "win?":
            team_rows.append(row)
            row += 1
        win_row = row
        # Free text sometimes spills into the column after the last boss.
        last_col = max(boss_cols) + 1
        attempts[int(m.group(1))] = {
            "columns": {
                col: [text(ws.cell(r, col).value) for r in team_rows]
                for col in range(BOSS_FIRST_COL, last_col + 1)
            },
            "boss_cols": boss_cols,
            "won": {col: ws.cell(win_row, col).value is True for col in boss_cols},
        }
        row += 1
    return attempts


def import_attempt(conn, number, enc, fights, names, ids, report):
    notes = ["Imported from spreadsheet."]
    cur = conn.execute("INSERT INTO attempts (number) VALUES (?)", (number,))
    attempt_id = cur.lastrowid

    box = []  # (catch_id, pokemon)
    for route, pokemon in (enc or {}).get("catches", {}).items():
        cur = conn.execute("INSERT INTO catches (attempt_id, route_id, pokemon, species) VALUES (?, ?, ?, ?)",
                           (attempt_id, ids["route"][route], pokemon, pokemon))
        box.append((cur.lastrowid, pokemon))

    free_text, latest_form = [], {}
    for col, cells in (fights or {}).get("columns", {}).items():
        boss = fights["boss_cols"].get(col)
        members, unmatched, text = match_team(cells, box, names)
        free_text += [t for t in text if t not in free_text]
        for cell in unmatched:
            report["team"].append(f"#{number} {boss or 'col ' + str(col)}: '{cell}' not in this attempt's box")
        if boss is None:
            continue
        won = fights["won"].get(col, False)
        if not members and not won:
            continue
        result = "won" if won else "lost"
        for battle_id in ids["boss"][boss]:
            cur = conn.execute("INSERT INTO fights (attempt_id, battle_id, result) VALUES (?, ?, ?)",
                               (attempt_id, battle_id, result))
            # Each team member is a copy with the form the sheet lists for this fight.
            conn.executemany("INSERT INTO fight_members (fight_id, slot, catch_id, species) VALUES (?, ?, ?, ?)",
                             [(cur.lastrowid, slot, c, species) for slot, (c, species) in enumerate(members, start=1)])
        latest_form.update(members)
        report["fights"][result] += 1
        if result == "lost":
            report["lost"].append(f"#{number} lost to {boss}")
    # The box holds each Pokemon in the latest form the sheet shows it in.
    conn.executemany("UPDATE catches SET species = ? WHERE id = ?",
                     [(species, catch_id) for catch_id, species in latest_form.items()])

    if free_text:
        notes.append("Run notes: " + " — ".join(free_text))
    deaths = (enc or {}).get("deaths", [])
    if deaths:
        notes.append("Deaths:\n" + "\n".join(f"- {d}" for d in deaths))
    conn.execute("UPDATE attempts SET notes = ? WHERE id = ?", ("\n".join(notes), attempt_id))
    report["catches"] += len(box)


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    replace = "--replace" in sys.argv
    xlsx = Path(args[0]) if args else DEFAULT_XLSX

    conn = db.connect()
    db.init_db(conn)
    names = Names(conn)
    ids = {
        "route": {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM routes")},
        "boss": db.level_cap_battles(conn),  # Past Boss Fights name -> battle ids
    }
    route_options = defaultdict(list)
    for r in conn.execute("SELECT DISTINCT r.name, e.pokemon FROM route_encounters e "
                          "JOIN routes r ON r.id = e.route_id ORDER BY e.position"):
        route_options[r["name"]].append(r["pokemon"])

    wb = openpyxl.load_workbook(xlsx, data_only=True)
    report = {"catch": [], "team": [], "lost": [], "fights": defaultdict(int), "catches": 0}
    encounters = read_encounters(wb["Past Encounters"], names, route_options, report)
    fights = read_boss_fights(wb["Past Boss Fights"], ids["boss"])

    existing = {r["number"] for r in conn.execute("SELECT number FROM attempts")}
    imported, skipped = [], []
    with conn:
        for number in sorted(set(encounters) | set(fights)):
            if number in existing:
                if not replace:
                    skipped.append(number)
                    continue
                conn.execute("DELETE FROM attempts WHERE number = ?", (number,))
            import_attempt(conn, number, encounters.get(number), fights.get(number), names, ids, report)
            imported.append(number)
    conn.close()

    print(f"Imported {len(imported)} attempts: {report['catches']} catches, "
          f"{report['fights']['won']} won fights, {report['fights']['lost']} lost fights.")
    if skipped:
        print(f"Skipped {len(skipped)} attempts that already exist (use --replace): {skipped}")
    sections = [
        ("Name corrections applied", [f"'{k}' -> {v}" for k, v in sorted(names.fixes.items())]),
        ("Fights recorded as lost (team listed, Win? unchecked)", report["lost"]),
        ("Catches skipped", report["catch"]),
        ("Team members skipped", report["team"]),
    ]
    for title, lines in sections:
        if lines:
            print(f"\n{title} ({len(lines)}):")
            for line in lines:
                print(f"  {line}")


if __name__ == "__main__":
    main()
