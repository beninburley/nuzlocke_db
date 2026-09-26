"""SQLite connection, schema setup and game-data loading."""
import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get("NUZLOCKE_DB", ROOT / "instance" / "nuzlocke.db"))
SCHEMA_PATH = ROOT / "schema.sql"
GAME_DATA_PATH = ROOT / "data" / "game_data.json"
SPRITES_PATH = ROOT / "data" / "sprites.json"


def connect(path=None):
    path = Path(path or DB_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn):
    """Create tables if missing and (re)load game data from data/game_data.json."""
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    load_game_data(conn)


def load_game_data(conn, path=GAME_DATA_PATH):
    """Sync game data into the DB.

    Routes and bosses are upserted by name so ids stay stable and existing
    catches/fights keep pointing at the right rows. Encounter tables and
    families are replaced wholesale.
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

        for position, boss in enumerate(data["bosses"]):
            conn.execute(
                "INSERT INTO bosses (name, level_cap, position) VALUES (?, ?, ?) "
                "ON CONFLICT (name) DO UPDATE SET level_cap = excluded.level_cap, "
                "position = excluded.position",
                (boss["name"], boss["level_cap"], position),
            )

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
