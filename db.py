"""SQLite connection, schema setup, migrations and game-data loading."""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NUZLOCKE_DB", ROOT / "instance" / "nuzlocke.db"))
SCHEMA_PATH = ROOT / "schema.sql"
# One folder per game, named by its slug: game.json ({"name"}), game_data.json (routes,
# battles, families) and, optionally, routing.json (when each route opens up, and areas
# sharing one encounter). The rest of data/ is shared by every game.
GAMES_DIR = ROOT / "data" / "games"
DEFAULT_GAME = "run-and-bun"  # the first game, and the one pages without a game in the URL use
SPRITES_PATH = ROOT / "data" / "sprites.json"
EVOLUTIONS_PATH = ROOT / "data" / "evolutions.json"
POKEDEX_PATH = ROOT / "data" / "pokedex.json"  # every move, ability and held item (PokeAPI)

# Bump when schema.sql changes in a way existing databases need migrating for,
# and add a step to migrate().
SCHEMA_VERSION = 7

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
    load_games(conn)
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
    if version < 6 and "game_id" not in columns(conn, "attempts"):
        backup(conn, "v5")
        migrate_games(conn)
    if version < 7:
        backup(conn, "v6")
        add_column(conn, "games", "data", "TEXT")  # v6 -> v7: games added on the admin page
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


# Databases from before v6 hold Run & Bun alone; rebuilt rows join it as game 1.
FIRST_GAME = f"INSERT OR IGNORE INTO games (id, slug, name) VALUES (1, '{DEFAULT_GAME}', 'Run & Bun');"


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
        conn.executescript("BEGIN;" + move_aside + schema_sql() + FIRST_GAME + copy_back + "COMMIT;")
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
        copy_back="INSERT INTO battles (id, game_id, key, name, level_cap, position)"
                  "  SELECT id, 1, 'boss:' || name, name, level_cap, position FROM bosses_v0;"
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
                  f"INSERT INTO attempts (id, user_id, game_id, number, notes, created_at)"
                  f"  SELECT id, (SELECT id FROM users WHERE username = '{owner}'), 1, number, notes, created_at"
                  f"  FROM attempts_v3;"
                  "DROP TABLE attempts_v3;",
        check=("attempts", "catches", "fights"),
    )


def migrate_games(conn):
    """v5 -> v6: games. Everything so far is Run & Bun's, now game 1: routes, battles,
    trainers' corrections and attempts get its id, and route names, battle and trainer
    keys, families and attempt numbers become unique per game. Rows keep their ids.

    Trainers and families are dropped rather than copied: game data reloads them.
    Tables a migration from before v5 already rebuilt have the new shape; they're left.
    """
    rebuilt = [table for table in ("routes", "battles", "trainer_edits", "attempts")
               if "game_id" not in columns(conn, table)]
    copy = {
        "routes": "INSERT INTO routes (id, game_id, name, position) SELECT id, 1, name, position FROM routes_v5;",
        "battles": "INSERT INTO battles (id, game_id, key, name, location, level_cap, group_id, position, split)"
                   "  SELECT id, 1, key, name, location, level_cap, group_id, position, split FROM battles_v5;",
        "trainer_edits": "INSERT INTO trainer_edits (game_id, trainer_key, pokemon, edited_by, edited_at)"
                         "  SELECT 1, trainer_key, pokemon, edited_by, edited_at FROM trainer_edits_v5;",
        "attempts": "INSERT INTO attempts (id, user_id, game_id, number, notes, created_at)"
                    "  SELECT id, user_id, 1, number, notes, created_at FROM attempts_v5;",
    }
    rebuild_tables(
        conn,
        move_aside="DROP TABLE IF EXISTS trainer_pokemon;"
                   "DROP TABLE IF EXISTS trainers;"
                   "DROP TABLE IF EXISTS species_families;"
                   + "".join(f"ALTER TABLE {table} RENAME TO {table}_v5;" for table in rebuilt),
        copy_back="".join(copy[table] + f"DROP TABLE {table}_v5;" for table in rebuilt),
        check=("routes", "battles", "trainer_edits", "attempts", "route_encounters", "routing_edits",
               "catches", "fights"),
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


def level_cap_battles(conn, game_id=None):
    """{split name: [battle ids]}: each split's level-cap battles, in game order, for one
    game (or, with none given, every game; only migrations from before games do that).

    Usually just one. A boss fight against two separate trainers has one per
    trainer; the last is the one that ends the split.
    """
    out = {}
    for row in conn.execute(
        "SELECT s.split, b.id FROM battles s "
        "JOIN battles b ON b.id = s.id OR (b.group_id = s.id AND b.level_cap IS NOT NULL) "
        "WHERE s.split IS NOT NULL AND (? IS NULL OR s.game_id = ?) ORDER BY s.position, b.position",
        (game_id, game_id),
    ):
        out.setdefault(row["split"], []).append(row["id"])
    return out


def game_slugs():
    """The slugs of the games with a folder under data/games/, in name order."""
    return sorted(d.name for d in GAMES_DIR.iterdir() if (d / "game_data.json").exists())


def game_file(slug, name):
    return GAMES_DIR / slug / name


def load_games(conn):
    """Sync every game into the DB: those with a folder in data/games/, then those added on
    the admin page (their game data is kept in games.data). Then the data the games share."""
    for slug in game_slugs():
        meta = json.loads(game_file(slug, "game.json").read_text(encoding="utf-8"))
        with conn:  # a folder takes over from an upload with the same slug
            conn.execute("INSERT INTO games (slug, name) VALUES (?, ?) "
                         "ON CONFLICT (slug) DO UPDATE SET name = excluded.name, data = NULL", (slug, meta["name"]))
        game_id = conn.execute("SELECT id FROM games WHERE slug = ?", (slug,)).fetchone()[0]
        load_game_data(conn, game_id, game_data(conn, game_by_slug(conn, slug)))
    for game in conn.execute("SELECT * FROM games WHERE data IS NOT NULL").fetchall():
        load_game_data(conn, game["id"], json.loads(game["data"]))
    load_shared_data(conn)


def game_data(conn, game):
    """A game's game_data.json, parsed: from its folder, or as added on the admin page."""
    if game["data"] is not None:
        return json.loads(game["data"])
    return json.loads(game_file(game["slug"], "game_data.json").read_text(encoding="utf-8"))


def add_game(conn, slug, name, data):
    """Add a game from the admin page (or replace one added there): `data` is a game_data.json
    that validate_game_data() passed. Returns its games row."""
    with conn:
        conn.execute("INSERT INTO games (slug, name, data) VALUES (?, ?, ?) "
                     "ON CONFLICT (slug) DO UPDATE SET name = excluded.name, data = excluded.data",
                     (slug, name, json.dumps(data, ensure_ascii=False)))
    game = game_by_slug(conn, slug)
    load_game_data(conn, game["id"], data)
    return game


def load_game_data(conn, game_id, data):
    """Sync one game's data (a parsed game_data.json) into the DB.

    Routes and battles are upserted by name/key so ids stay stable and
    existing catches/fights keep pointing at the right rows. Encounter tables,
    trainers and families are replaced wholesale.
    """
    with conn:
        for position, route in enumerate(data["routes"]):
            conn.execute(
                "INSERT INTO routes (game_id, name, position) VALUES (?, ?, ?) "
                "ON CONFLICT (game_id, name) DO UPDATE SET position = excluded.position",
                (game_id, route["name"], position),
            )
        route_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id, name FROM routes WHERE game_id = ?", (game_id,))}

        conn.execute("DELETE FROM route_encounters WHERE route_id IN (SELECT id FROM routes WHERE game_id = ?)", (game_id,))
        conn.executemany(
            "INSERT INTO route_encounters (route_id, method, pokemon, rate, level, position) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            [
                (route_ids[route["name"]], e["method"], e["pokemon"], e["rate"], e["level"], i)
                for route in data["routes"]
                for i, e in enumerate(route["encounters"])
            ],
        )

        load_battles(conn, game_id, data["battles"])

        conn.execute("DELETE FROM species_families WHERE game_id = ?", (game_id,))
        conn.executemany(
            "INSERT OR IGNORE INTO species_families (game_id, species, family_id) VALUES (?, ?, ?)",
            [(game_id, species, fid) for fid, family in enumerate(data["families"]) for species in family],
        )


def load_shared_data(conn):
    """Sprites and evolutionary lines (PokeAPI): the same for every game."""
    with conn:
        # Every species the app knows: the games', plus the whole Pokédex
        # (scripts/fetch_pokedex.py). A few have no sprite on PokeAPI yet: ''.
        conn.execute("DELETE FROM species_sprites")
        if SPRITES_PATH.exists():
            sprites = json.loads(SPRITES_PATH.read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT INTO species_sprites (species, url) VALUES (?, ?)",
                [(species, url or "") for species, url in sprites.items()],
            )

        conn.execute("DELETE FROM evolution_lines")
        if EVOLUTIONS_PATH.exists():
            lines = json.loads(EVOLUTIONS_PATH.read_text(encoding="utf-8"))
            conn.executemany(
                "INSERT INTO evolution_lines (species, members) VALUES (?, ?)",
                [(species, json.dumps(members)) for species, members in lines.items()],
            )


def load_battles(conn, game_id, battles):
    for position, battle in enumerate(battles):
        conn.execute(
            "INSERT INTO battles (game_id, key, name, location, level_cap, position, split) VALUES (?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (game_id, key) DO UPDATE SET name = excluded.name, location = excluded.location, "
            "level_cap = excluded.level_cap, position = excluded.position, split = excluded.split",
            (game_id, battle["key"], battle["name"], battle["location"], battle["level_cap"], position, battle["split"]),
        )
    battle_ids = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM battles WHERE game_id = ?", (game_id,))}
    conn.executemany(
        "UPDATE battles SET group_id = ? WHERE game_id = ? AND key = ?",
        [(battle_ids[f"boss:{b['group']}"] if b["group"] else None, game_id, b["key"]) for b in battles],
    )
    # Battles that left the game data go too, unless an attempt recorded a fight there.
    current = [b["key"] for b in battles]
    conn.execute(
        f"DELETE FROM battles WHERE game_id = ? AND key NOT IN ({','.join('?' * len(current))}) "
        "AND id NOT IN (SELECT battle_id FROM fights)",
        (game_id, *current),
    )

    # Cascades to trainer_pokemon
    conn.execute("DELETE FROM trainers WHERE battle_id IN (SELECT id FROM battles WHERE game_id = ?)", (game_id,))
    edits = {r["trainer_key"]: json.loads(r["pokemon"])
             for r in conn.execute("SELECT trainer_key, pokemon FROM trainer_edits WHERE game_id = ?", (game_id,))}
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


def pokedex_names():
    """{"moves", "abilities", "items"}: every name PokeAPI has (empty lists without the file)."""
    if not POKEDEX_PATH.exists():
        return {"moves": [], "abilities": [], "items": []}
    data = json.loads(POKEDEX_PATH.read_text(encoding="utf-8"))
    return {key: data.get(key, []) for key in ("moves", "abilities", "items")}


def routing_defaults(conn, game):
    """{route name: {"unlock": split or None, "area": area or None}} for every route of `game`
    (a games row), from its routing.json. A route the file doesn't list (or every route, with
    no file) is open from the start and in no area. Raises ValueError for a route or split the
    game data doesn't have, or a route listed twice."""
    path = game_file(game["slug"], "routing.json")
    data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"unlocks": [], "areas": {}}
    routes = [r[0] for r in conn.execute("SELECT name FROM routes WHERE game_id = ? ORDER BY position", (game["id"],))]
    splits = {r[0] for r in conn.execute("SELECT split FROM battles WHERE game_id = ? AND split IS NOT NULL", (game["id"],))}
    result = {name: {"unlock": None, "area": None} for name in routes}
    seen = {"unlock": set(), "area": set()}

    def claim(kind, name, value):
        if name not in result:
            raise ValueError(f"{game['slug']}/routing.json: no route named {name!r}")
        if name in seen[kind]:
            raise ValueError(f"{game['slug']}/routing.json: {name!r} is listed twice under {kind}s")
        seen[kind].add(name)
        result[name][kind] = value

    for step in data["unlocks"]:
        if step["after"] is not None and step["after"] not in splits:
            raise ValueError(f"{game['slug']}/routing.json: no split named {step['after']!r}")
        for name in step["routes"]:
            claim("unlock", name, step["after"])
    for area, names in data["areas"].items():
        for name in names:
            claim("area", name, area)
    return result


def routing(conn, game):
    """{route name: {"unlock", "area", "default_unlock", "edited": {"by", "at"} or None}}: the game's
    defaults with the admins' changes (routing_edits) applied. A change naming a split that's no longer
    in the game data is ignored."""
    result = routing_defaults(conn, game)
    for info in result.values():
        info.update(default_unlock=info["unlock"], edited=None)
    splits = {r[0] for r in conn.execute("SELECT split FROM battles WHERE game_id = ? AND split IS NOT NULL", (game["id"],))}
    for edit in conn.execute(
        "SELECT r.name, e.unlock, e.edited_at, u.username FROM routing_edits e "
        "JOIN routes r ON r.id = e.route_id LEFT JOIN users u ON u.id = e.edited_by WHERE r.game_id = ?", (game["id"],)
    ):
        if edit["name"] in result and (edit["unlock"] is None or edit["unlock"] in splits):
            result[edit["name"]].update(unlock=edit["unlock"], edited={"by": edit["username"], "at": edit["edited_at"]})
    return result


def original_trainer_team(conn, game, trainer_key):
    """A trainer's team as `game`'s data (the spreadsheet) has it, or None."""
    for battle in game_data(conn, game)["battles"]:
        for trainer in battle["trainers"]:
            if trainer["key"] == trainer_key:
                return trainer["pokemon"]
    return None


def game_by_slug(conn, slug):
    """A games row, or None."""
    return conn.execute("SELECT * FROM games WHERE slug = ?", (slug,)).fetchone()


# ---------------------------------------------------------------------------
# Checking a game_data.json added on the admin page
# ---------------------------------------------------------------------------

MAX_PROBLEMS = 20  # reported at once


def validate_game_data(data):
    """What's wrong with a game_data.json, as a list of sentences (empty when it's fine).

    {"routes": [{name, encounters: [{method, pokemon, rate, level}]}],
     "battles": [{key, name, location, level_cap, split, group,
                  trainers: [{key, name, location, tags, pokemon: [{species, level, item, ability, nature, moves}]}]}],
     "families": [[species, ...]]}
    Route names, battle keys, trainer keys and split names are unique. A battle with a
    `split` ends that split and has a level cap; a battle's `group` names the split it
    belongs to, whose battle has the key "boss:<group>". Anything else (like "source") is ignored.
    """
    problems = []

    def problem(text):
        if len(problems) < MAX_PROBLEMS:
            problems.append(text)

    def text(value, where, optional=False):
        if value is None and optional:
            return True
        if not isinstance(value, str) or not value.strip():
            problem(f"{where} should be text{' or null' if optional else ''}.")
            return False
        return True

    def number(value, where, low, high, optional=True):
        if value is None and optional:
            return
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            problem(f"{where} should be a number from {low} to {high}{' or null' if optional else ''}.")

    def items(value, where):
        if not isinstance(value, list):
            problem(f"{where} should be a list.")
            return []
        return value

    if not isinstance(data, dict):
        return ["The file should be a JSON object with routes, battles and families."]
    for key in ("routes", "battles", "families"):
        if key not in data:
            problem(f'The file has no \"{key}\".')
    data = {"routes": [], "battles": [], "families": [], **data}  # check the rest anyway

    routes = items(data["routes"], "routes")
    if not routes and not problems:
        problem("A game needs at least one route.")
    names = set()
    for i, route in enumerate(routes):
        where = f"Route {i + 1}"
        if not isinstance(route, dict):
            problem(f"{where} should be an object with a name and encounters.")
            continue
        if text(route.get("name"), f"{where}'s name"):
            where = f"Route \"{route['name']}\""
            if route["name"] in names:
                problem(f"{where} is listed twice.")
            names.add(route["name"])
        for j, e in enumerate(items(route.get("encounters"), f"{where}'s encounters")):
            at = f"{where}, encounter {j + 1}"
            if not isinstance(e, dict):
                problem(f"{at} should be an object with method, pokemon, rate and level.")
                continue
            text(e.get("method"), f"{at}: method")
            text(e.get("pokemon"), f"{at}: pokemon")
            number(e.get("rate"), f"{at}: rate", 0, 100)
            text(e.get("level"), f"{at}: level", optional=True)

    battles = items(data["battles"], "battles")
    keys, splits, trainer_keys = set(), set(), set()
    for battle in battles:
        if isinstance(battle, dict) and isinstance(battle.get("key"), str):
            keys.add(battle["key"])
    seen = set()
    for i, battle in enumerate(battles):
        where = f"Battle {i + 1}"
        if not isinstance(battle, dict):
            problem(f"{where} should be an object.")
            continue
        if text(battle.get("key"), f"{where}'s key"):
            if battle["key"] in seen:
                problem(f"Battle key \"{battle['key']}\" is used twice.")
            seen.add(battle["key"])
        if text(battle.get("name"), f"{where}'s name"):
            where = f"Battle \"{battle['name']}\""
        text(battle.get("location"), f"{where}'s location", optional=True)
        number(battle.get("level_cap"), f"{where}'s level_cap", 1, 100)
        split, group = battle.get("split"), battle.get("group")
        if text(split, f"{where}'s split", optional=True) and split is not None:
            if split in splits:
                problem(f"The split \"{split}\" is ended by two battles.")
            splits.add(split)
            if battle.get("level_cap") is None:
                problem(f"{where} ends the \"{split}\" split, so it needs a level_cap.")
        if text(group, f"{where}'s group", optional=True) and group is not None:
            if split is not None:
                problem(f"{where} has both a split and a group; a battle either ends a split or belongs to one.")
            elif f"boss:{group}" not in keys:
                problem(f"{where}'s group \"{group}\" has no battle with the key \"boss:{group}\".")
        for j, trainer in enumerate(items(battle.get("trainers"), f"{where}'s trainers")):
            at = f"{where}, trainer {j + 1}"
            if not isinstance(trainer, dict):
                problem(f"{at} should be an object.")
                continue
            if text(trainer.get("key"), f"{at}: key"):
                if trainer["key"] in trainer_keys:
                    problem(f"Trainer key \"{trainer['key']}\" is used twice.")
                trainer_keys.add(trainer["key"])
            text(trainer.get("name"), f"{at}: name")
            text(trainer.get("location"), f"{at}: location", optional=True)
            tags = items(trainer.get("tags"), f"{at}: tags")
            if any(not isinstance(tag, str) for tag in tags):
                problem(f"{at}: tags should be text.")
            team = items(trainer.get("pokemon"), f"{at}: pokemon")
            if not 1 <= len(team) <= 6:
                problem(f"{at} has {len(team)} Pokémon; a team has 1 to 6.")
            for k, mon in enumerate(team):
                mon_at = f"{at}, Pokémon {k + 1}"
                if not isinstance(mon, dict):
                    problem(f"{mon_at} should be an object.")
                    continue
                text(mon.get("species"), f"{mon_at}: species")
                number(mon.get("level"), f"{mon_at}: level", 1, 100)
                for field in ("item", "ability", "nature"):
                    text(mon.get(field), f"{mon_at}: {field}", optional=True)
                moves = items(mon.get("moves"), f"{mon_at}: moves")
                if len(moves) > 4 or any(not isinstance(m, str) or not m.strip() for m in moves):
                    problem(f"{mon_at}: moves should be up to 4 names.")

    for i, family in enumerate(items(data["families"], "families")):
        if not isinstance(family, list) or not family or any(not isinstance(s, str) or not s.strip() for s in family):
            problem(f"Family {i + 1} should be a list of species names.")
    return problems
