"""SQLite connection, schema setup, migrations and game-data loading."""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NUZLOCKE_DB", ROOT / "instance" / "nuzlocke.db"))
SCHEMA_PATH = ROOT / "schema.sql"
GAME_DATA_PATH = ROOT / "data" / "game_data.json"
SPRITES_PATH = ROOT / "data" / "sprites.json"
EVOLUTIONS_PATH = ROOT / "data" / "evolutions.json"

# Bump when schema.sql changes in a way existing databases need migrating for,
# and add a step to migrate().
SCHEMA_VERSION = 2

# A Pokemon's details, as stored on box Pokemon (catches) and on the copies in
# battle teams (fight_members).
IV_STATS = ("hp", "atk", "def", "spa", "spd", "spe")
DETAIL_COLUMNS = ("level", "ability", "nature", "item", "move1", "move2", "move3", "move4",
                  *(f"iv_{stat}" for stat in IV_STATS), "status")
POKEMON_COLUMNS = ("species", *DETAIL_COLUMNS)
STATUSES = ("OK", "Burn", "Sleep", "Fainted")
NATURES = ("Hardy", "Lonely", "Brave", "Adamant", "Naughty", "Bold", "Docile", "Relaxed", "Impish",
           "Lax", "Timid", "Hasty", "Serious", "Jolly", "Naive", "Modest", "Mild", "Quiet", "Bashful",
           "Rash", "Calm", "Gentle", "Sassy", "Careful", "Quirky")


def connect(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Migrate old databases, create missing tables and (re)load game data."""
    migrate(conn)
    conn.executescript(schema_sql())
    load_game_data(conn)


def schema_sql():
    return SCHEMA_PATH.read_text(encoding="utf-8")


def migrate(conn):
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "catches" not in tables:  # new database: schema.sql creates everything
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        return
    if version < 1 and "bosses" in tables:
        backup(conn, "v0")
        migrate_bosses_to_battles(conn)
        version = 1
    if version < 2:
        backup(conn, "v1")
        migrate_box_details(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def backup(conn, label):
    """Copy the database next to itself before a migration touches it."""
    path = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    target = sqlite3.connect(path.with_name(f"{path.stem}.backup-{label}{path.suffix}"))
    with target:
        conn.backup(target)
    target.close()


def rebuild_tables(conn, move_aside, copy_back):
    """SQLite's table-rebuild procedure, in one transaction.

    With foreign keys off and legacy renames (so other tables' references keep
    pointing at the original names), `move_aside` renames the old tables,
    schema.sql creates the new ones, and `copy_back` copies rows over (keeping
    ids) and drops the old tables. Triggers on or about the rebuilt tables must
    be dropped in `move_aside`; schema.sql recreates them.
    """
    conn.execute("PRAGMA foreign_keys = OFF")
    conn.execute("PRAGMA legacy_alter_table = ON")
    try:
        conn.executescript("BEGIN;" + move_aside + schema_sql() + copy_back + "COMMIT;")
    except sqlite3.Error:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.execute("PRAGMA legacy_alter_table = OFF")
        conn.execute("PRAGMA foreign_keys = ON")
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"migration left broken references: {[tuple(p) for p in problems]}")


def migrate_bosses_to_battles(conn):
    """v0 -> v1: `bosses` (23 level-cap fights) becomes `battles` (every trainer).

    Rows keep their ids, so recorded fights stay attached to their boss.
    """
    rebuild_tables(
        conn,
        move_aside="DROP TRIGGER IF EXISTS fight_members_same_attempt;"
                   "ALTER TABLE fights RENAME TO fights_v0;"
                   "ALTER TABLE bosses RENAME TO bosses_v0;",
        copy_back="INSERT INTO battles (id, key, name, level_cap, position)"
                  "  SELECT id, 'boss:' || name, name, level_cap, position FROM bosses_v0;"
                  "INSERT INTO fights (id, attempt_id, battle_id, result)"
                  "  SELECT id, attempt_id, boss_id, result FROM fights_v0;"
                  "DROP TABLE fights_v0;"
                  "DROP TABLE bosses_v0;",
    )


def migrate_box_details(conn):
    """v1 -> v2: box Pokemon get details, and battle teams hold copies of them.

    Each catch's current species starts as what was caught. Each team member
    becomes a copy of its catch as it is now (just the species, since no
    details exist yet); scripts/backfill_forms.py can then fill in the evolved
    forms the spreadsheet recorded.
    """
    rebuild_tables(
        conn,
        move_aside="DROP TRIGGER IF EXISTS catches_valid_insert;"
                   "DROP TRIGGER IF EXISTS catches_valid_update;"
                   "DROP TRIGGER IF EXISTS fight_members_same_attempt;"
                   "ALTER TABLE catches RENAME TO catches_v1;"
                   "ALTER TABLE fight_members RENAME TO fight_members_v1;",
        copy_back="INSERT INTO catches (id, attempt_id, route_id, pokemon, species)"
                  "  SELECT id, attempt_id, route_id, pokemon, pokemon FROM catches_v1;"
                  "INSERT INTO fight_members (fight_id, slot, catch_id, species)"
                  "  SELECT m.fight_id, m.slot, m.catch_id, c.pokemon"
                  "  FROM fight_members_v1 m JOIN catches_v1 c ON c.id = m.catch_id"
                  "  ORDER BY m.fight_id, m.slot;"
                  "DROP TABLE fight_members_v1;"
                  "DROP TABLE catches_v1;",
    )


def load_game_data(conn, path=GAME_DATA_PATH):
    """Sync game data into the DB.

    Routes and battles are upserted by name/key so ids stay stable and
    existing catches/fights keep pointing at the right rows. Encounter tables,
    trainers and families are replaced wholesale.
    """
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    with conn:
        for position, route in enumerate(data["routes"]):
            conn.execute(
                "INSERT INTO routes (name, position) VALUES (?, ?) "
                "ON CONFLICT (name) DO UPDATE SET position = excluded.position",
                (route["name"], position),
            )
        route_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM routes")}

        conn.execute("DELETE FROM route_encounters")
        conn.executemany(
            "INSERT INTO route_encounters (route_id, method, pokemon, rate, level, position) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (route_ids[route["name"]], e["method"], e["pokemon"], e["rate"], e["level"], i)
                for route in data["routes"]
                for i, e in enumerate(route["encounters"])
            ],
        )

        load_battles(conn, data["battles"])

        conn.execute("DELETE FROM species_families")
        conn.executemany(
            "INSERT OR IGNORE INTO species_families (species, family_id) VALUES (?, ?)",
            [(species, fid) for fid, family in enumerate(data["families"]) for species in family],
        )

        conn.execute("DELETE FROM species_sprites")
        if SPRITES_PATH.exists():
            sprites = json.loads(SPRITES_PATH.read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT INTO species_sprites (species, url) VALUES (?, ?)",
                [(species, url) for species, url in sprites.items() if url],
            )

        conn.execute("DELETE FROM evolution_lines")
        if EVOLUTIONS_PATH.exists():
            lines = json.loads(EVOLUTIONS_PATH.read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT INTO evolution_lines (species, members) VALUES (?, ?)",
                [(species, json.dumps(members)) for species, members in lines.items()],
            )


def load_battles(conn, battles):
    for position, battle in enumerate(battles):
        conn.execute(
            "INSERT INTO battles (key, name, location, level_cap, position) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET name = excluded.name, location = excluded.location, "
            "level_cap = excluded.level_cap, position = excluded.position",
            (battle["key"], battle["name"], battle["location"], battle["level_cap"], position),
        )
    battle_ids = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM battles")}
    conn.executemany(
        "UPDATE battles SET group_id = ? WHERE key = ?",
        [(battle_ids[f"boss:{b['group']}"] if b["group"] else None, b["key"]) for b in battles],
    )
    # Battles that left the game data go too, unless an attempt recorded a fight there.
    current = [b["key"] for b in battles]
    conn.execute(
        f"DELETE FROM battles WHERE key NOT IN ({','.join('?' * len(current))}) "
        "AND id NOT IN (SELECT battle_id FROM fights)",
        current,
    )

    conn.execute("DELETE FROM trainers")  # cascades to trainer_pokemon
    position = 0
    for battle in battles:
        for trainer in battle["trainers"]:
            cur = conn.execute(
                "INSERT INTO trainers (battle_id, key, name, location, tags, position) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (battle_ids[battle["key"]], trainer["key"], trainer["name"], trainer["location"],
                 ",".join(trainer["tags"]), position),
            )
            position += 1
            conn.executemany(
                "INSERT INTO trainer_pokemon (trainer_id, slot, species, level, item, ability, "
                "nature, move1, move2, move3, move4) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [(cur.lastrowid, slot, p["species"], p["level"], p["item"], p["ability"],
                  p["nature"], *(p["moves"] + [None] * 4)[:4])
                 for slot, p in enumerate(trainer["pokemon"], start=1)],
            )
