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
SCHEMA_VERSION = 5

# The site owner's account. Attempts recorded before accounts existed are
# given to it (as an admin, without a password until one is set with
# scripts/manage_account.py), and the import scripts use it by default.
SITE_OWNER = "bkewps"

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
    version = migrate(conn)
    conn.executescript(schema_sql())
    load_game_data(conn)
    if version < 3:
        split_level_cap_fights(conn)
    conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def schema_sql():
    return SCHEMA_PATH.read_text(encoding="utf-8")


def migrate(conn):
    """Bring an existing database's tables up to date, before schema.sql runs.

    Returns the version it was at. Steps that need the game data loaded run
    in init_db afterwards, which then sets the final version.
    """
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    if "catches" not in tables:  # new database: schema.sql creates everything
        return SCHEMA_VERSION
    if version < 1 and "bosses" in tables:
        backup(conn, "v0")
        migrate_bosses_to_battles(conn)
        conn.execute("PRAGMA user_version = 1")
    if version < 2:
        backup(conn, "v1")
        migrate_box_details(conn)
        conn.execute("PRAGMA user_version = 2")
    if version < 3:
        backup(conn, "v2")
        # Safe to repeat, so an upgrade to v3 that stopped halfway just carries on.
        add_column(conn, "battles", "split", "TEXT")
        add_column(conn, "fights", "trainer_key", "TEXT")
    if version < 4 and "user_id" not in columns(conn, "attempts"):
        backup(conn, "v3")
        migrate_accounts(conn)
    if version < 5:
        backup(conn, "v4")
        add_column(conn, "fights", "notes", "TEXT NOT NULL DEFAULT ''")  # v4 -> v5: notes per battle
    problems = conn.execute("PRAGMA foreign_key_check").fetchall()
    if problems:
        raise RuntimeError(f"migration left broken references: {[tuple(p) for p in problems]}")
    return version


def columns(conn, table):
    return {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}


def add_column(conn, table, column, definition):
    if column not in columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def backup(conn, label):
    """Copy the database next to itself before a migration touches it."""
    path = Path(conn.execute("PRAGMA database_list").fetchone()["file"])
    target = sqlite3.connect(path.with_name(f"{path.stem}.backup-{label}{path.suffix}"))
    with target:
        conn.backup(target)
    target.close()


def rebuild_tables(conn, move_aside, copy_back, check):
    """SQLite's table-rebuild procedure, in one transaction.

    With foreign keys off and legacy renames (so other tables' references keep
    pointing at the original names), `move_aside` renames the old tables,
    schema.sql creates the new ones, and `copy_back` copies rows over (keeping
    ids) and drops the old tables. Triggers on or about the rebuilt tables must
    be dropped in `move_aside`; schema.sql recreates them.

    Afterwards the references from the `check` tables are verified. Only those:
    tables that later migrations rebuild may not fit the current schema yet.
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
    problems = [p for table in check for p in conn.execute(f"PRAGMA foreign_key_check({table})")]
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
        check=("battles", "fights", "fight_members"),
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
        check=("catches", "fights", "fight_members"),
    )


def migrate_accounts(conn):
    """v3 -> v4: accounts. Every attempt belongs to a user, and attempt
    numbers are unique per user rather than site-wide.

    Existing attempts go to SITE_OWNER, created as an admin with no password
    (it can't log in until one is set with scripts/manage_account.py).
    """
    owner = SITE_OWNER.replace("'", "''")
    rebuild_tables(
        conn,
        move_aside="ALTER TABLE attempts RENAME TO attempts_v3;",
        copy_back=f"INSERT OR IGNORE INTO users (username, role)"
                  f"  SELECT '{owner}', 'admin' WHERE EXISTS (SELECT 1 FROM attempts_v3);"
                  f"INSERT INTO attempts (id, user_id, number, notes, created_at)"
                  f"  SELECT id, (SELECT id FROM users WHERE username = '{owner}'), number, notes, created_at"
                  f"  FROM attempts_v3;"
                  "DROP TABLE attempts_v3;",
        check=("attempts", "catches", "fights"),
    )


def split_level_cap_fights(conn):
    """v2 -> v3, once game data is loaded.

    A boss fight against two trainers with separate teams (the Museum grunts,
    Tate & Liza) became one battle per trainer; recorded fights stay on the
    last one. Each attempt that recorded the fight gets the same result and a
    copy of the same team on the others. Safe to repeat.
    """
    columns = ", ".join(POKEMON_COLUMNS)
    with conn:
        for battle_ids in level_cap_battles(conn).values():
            *added, original = battle_ids
            for battle_id in added:
                for fight in conn.execute(
                    "SELECT id, attempt_id, result FROM fights WHERE battle_id = ? AND attempt_id NOT IN "
                    "(SELECT attempt_id FROM fights WHERE battle_id = ?)", (original, battle_id)
                ).fetchall():
                    cur = conn.execute("INSERT INTO fights (attempt_id, battle_id, result) VALUES (?, ?, ?)",
                                       (fight["attempt_id"], battle_id, fight["result"]))
                    conn.execute(
                        f"INSERT INTO fight_members (fight_id, slot, catch_id, {columns}) "
                        f"SELECT ?, slot, catch_id, {columns} FROM fight_members WHERE fight_id = ? ORDER BY slot",
                        (cur.lastrowid, fight["id"]))


def level_cap_battles(conn):
    """{split name: [battle ids]}: each split's level-cap battles, in game order.

    Usually just one. A boss fight against two separate trainers has one per
    trainer; the last is the one that ends the split.
    """
    out = {}
    for row in conn.execute(
        "SELECT s.split, b.id FROM battles s "
        "JOIN battles b ON b.id = s.id OR (b.group_id = s.id AND b.level_cap IS NOT NULL) "
        "WHERE s.split IS NOT NULL ORDER BY s.position, b.position"
    ):
        out.setdefault(row["split"], []).append(row["id"])
    return out


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
            "INSERT INTO battles (key, name, location, level_cap, position, split) VALUES (?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (key) DO UPDATE SET name = excluded.name, location = excluded.location, "
            "level_cap = excluded.level_cap, position = excluded.position, split = excluded.split",
            (battle["key"], battle["name"], battle["location"], battle["level_cap"], position, battle["split"]),
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
    edits = {r["trainer_key"]: json.loads(r["pokemon"])
             for r in conn.execute("SELECT trainer_key, pokemon FROM trainer_edits")}
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
            # An admin's correction to this team wins over the spreadsheet's.
            set_trainer_team(conn, cur.lastrowid, edits.get(trainer["key"], trainer["pokemon"]))


def set_trainer_team(conn, trainer_id, pokemon):
    """Replace a trainer's team with `pokemon`: [{species, level, item, ability, nature, moves}]."""
    conn.execute("DELETE FROM trainer_pokemon WHERE trainer_id = ?", (trainer_id,))
    conn.executemany(
        "INSERT INTO trainer_pokemon (trainer_id, slot, species, level, item, ability, "
        "nature, move1, move2, move3, move4) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(trainer_id, slot, p["species"], p["level"], p["item"], p["ability"],
          p["nature"], *(list(p["moves"]) + [None] * 4)[:4])
         for slot, p in enumerate(pokemon, start=1)],
    )


def original_trainer_team(trainer_key, path=GAME_DATA_PATH):
    """A trainer's team as the game data (the spreadsheet) has it, or None."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    for battle in data["battles"]:
        for trainer in battle["trainers"]:
            if trainer["key"] == trainer_key:
                return trainer["pokemon"]
    return None
