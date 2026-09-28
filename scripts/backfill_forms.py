"""One-off: give existing battle copies the forms the spreadsheet recorded.

The v2 migration turned every battle-team member into a copy of its box
Pokemon as caught, so #101's Brawly team shows Turtwig where the Past Boss
Fights tab says Grotle. For fights imported from that tab, this sets:
  * each team copy's species to the form the sheet lists for that fight, and
  * each box Pokemon's current species to the latest form the sheet shows.
Only copies and box Pokemon still showing their caught species are changed, so
anything edited in the app since is left alone. Safe to re-run.

Usage:
    python scripts/backfill_forms.py ["path/to/sheet.xlsx"] [--dry-run]
"""
import sys
from pathlib import Path

import openpyxl

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import db  # noqa: E402
from import_history import DEFAULT_XLSX, Names, match_team, read_boss_fights  # noqa: E402


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry_run = "--dry-run" in sys.argv
    xlsx = Path(args[0]) if args else DEFAULT_XLSX

    conn = db.connect()
    db.init_db(conn)
    names = Names(conn)
    bosses = {r["name"]: r["id"] for r in conn.execute(
        "SELECT id, name FROM battles WHERE level_cap IS NOT NULL")}
    sheet = read_boss_fights(openpyxl.load_workbook(xlsx, data_only=True)["Past Boss Fights"], bosses)

    copies, box, examples = 0, 0, []
    for number, fights in sorted(sheet.items()):
        attempt = conn.execute("SELECT id FROM attempts WHERE number = ?", (number,)).fetchone()
        if attempt is None:
            continue
        caught = {r["id"]: r["pokemon"] for r in conn.execute(
            "SELECT id, pokemon FROM catches WHERE attempt_id = ? ORDER BY id", (attempt["id"],))}
        latest = {}
        for col, cells in fights["columns"].items():
            members, _, _ = match_team(cells, list(caught.items()), names)
            latest.update(members)
            boss = fights["boss_cols"].get(col)
            fight = boss and conn.execute("SELECT id FROM fights WHERE attempt_id = ? AND battle_id = ?",
                                          (attempt["id"], bosses[boss])).fetchone()
            if not fight:
                continue
            for catch_id, species in members:
                changed = conn.execute(
                    "UPDATE fight_members SET species = ? "
                    "WHERE fight_id = ? AND catch_id = ? AND species = ? AND species <> ?",
                    (species, fight["id"], catch_id, caught[catch_id], species)).rowcount
                copies += changed
                if changed and len(examples) < 5:
                    examples.append(f"#{number} {boss}: {caught[catch_id]} -> {species}")
        for catch_id, species in latest.items():
            box += conn.execute(
                "UPDATE catches SET species = ? WHERE id = ? AND species = pokemon AND pokemon <> ?",
                (species, catch_id, species)).rowcount

    if dry_run:
        conn.rollback()
    else:
        conn.commit()
    conn.close()
    verb = "Would update" if dry_run else "Updated"
    print(f"{verb} {copies} battle copies and {box} box Pokemon with the forms the sheet recorded.")
    for line in examples:
        print(f"  e.g. {line}")


if __name__ == "__main__":
    main()
