"""Nuzlocke tracker: JSON API + static frontend.

Run with:  python app.py   (then open http://127.0.0.1:5000)
"""
import json
import sqlite3

from flask import Flask, g, jsonify, request

import db

app = Flask(__name__, static_folder="static", static_url_path="")

TEAM_SIZE = 6
RESULTS = (None, "won", "lost")


class ApiError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message = message
        self.status = status


@app.errorhandler(ApiError)
def handle_api_error(err):
    return jsonify(error=err.message), err.status


def get_db():
    if "db" not in g:
        g.db = db.connect()
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def body():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise ApiError("expected a JSON object body")
    return data


def get_attempt(conn, attempt_id):
    row = conn.execute("SELECT * FROM attempts WHERE id = ?", (attempt_id,)).fetchone()
    if row is None:
        raise ApiError("attempt not found", 404)
    return row


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------

@app.get("/")
def index():
    return app.send_static_file("index.html")


# ---------------------------------------------------------------------------
# Game data (read-only)
# ---------------------------------------------------------------------------

@app.get("/api/game")
def game():
    conn = get_db()
    routes = [dict(r, options=[]) for r in conn.execute(
        "SELECT id, name FROM routes ORDER BY position")]
    by_id = {r["id"]: r for r in routes}
    # Collapse duplicate encounter slots into one option per (method, pokemon).
    for row in conn.execute(
        "SELECT route_id, method, pokemon, SUM(rate) AS rate, "
        "       GROUP_CONCAT(DISTINCT level) AS levels "
        "FROM route_encounters GROUP BY route_id, method, pokemon "
        "ORDER BY route_id, MIN(position)"
    ):
        by_id[row["route_id"]]["options"].append({
            "method": row["method"],
            "pokemon": row["pokemon"],
            "rate": round(row["rate"], 2) if row["rate"] is not None else None,
            "levels": row["levels"],
        })
    battles = [dict(b, tags=[]) for b in conn.execute(
        "SELECT id, name, location, level_cap, group_id FROM battles ORDER BY position")]
    by_battle = {b["id"]: b for b in battles}
    for trainer in conn.execute("SELECT battle_id, tags FROM trainers ORDER BY position"):
        tags = by_battle[trainer["battle_id"]]["tags"]
        tags.extend(t for t in trainer["tags"].split(",") if t and t not in tags)
    sprites = {r["species"]: r["url"] for r in conn.execute("SELECT species, url FROM species_sprites")}
    evolutions = {r["species"]: json.loads(r["members"])
                  for r in conn.execute("SELECT species, members FROM evolution_lines")}
    # Autocomplete for box Pokemon details: the names Run & Bun's own trainers use.
    distinct = lambda sql: [r[0] for r in conn.execute(sql)]  # noqa: E731
    suggestions = {
        "abilities": distinct("SELECT DISTINCT ability FROM trainer_pokemon WHERE ability IS NOT NULL ORDER BY 1"),
        "items": distinct("SELECT DISTINCT item FROM trainer_pokemon WHERE item IS NOT NULL ORDER BY 1"),
        "moves": distinct(" UNION ".join(
            f"SELECT move{i} FROM trainer_pokemon WHERE move{i} IS NOT NULL" for i in range(1, 5)) + " ORDER BY 1"),
    }
    return jsonify(routes=routes, battles=battles, sprites=sprites, evolutions=evolutions,
                   suggestions=suggestions, natures=db.NATURES, statuses=db.STATUSES, iv_stats=db.IV_STATS)


@app.get("/api/battles/<int:battle_id>")
def battle_detail(battle_id):
    """A battle's trainers and their full teams (item, ability, nature, moves)."""
    conn = get_db()
    battle = conn.execute(
        "SELECT id, name, location, level_cap, group_id FROM battles WHERE id = ?",
        (battle_id,)).fetchone()
    if battle is None:
        raise ApiError("battle not found", 404)
    trainers = [dict(t, tags=[x for x in t["tags"].split(",") if x], pokemon=[])
                for t in conn.execute(
                    "SELECT id, name, location, tags FROM trainers "
                    "WHERE battle_id = ? ORDER BY position", (battle_id,))]
    by_trainer = {t["id"]: t for t in trainers}
    for p in conn.execute(
        "SELECT p.* FROM trainer_pokemon p JOIN trainers t ON t.id = p.trainer_id "
        "WHERE t.battle_id = ? ORDER BY p.trainer_id, p.slot", (battle_id,)
    ):
        by_trainer[p["trainer_id"]]["pokemon"].append({
            "slot": p["slot"],
            "species": p["species"],
            "level": p["level"],
            "item": p["item"],
            "ability": p["ability"],
            "nature": p["nature"],
            "moves": [m for m in (p["move1"], p["move2"], p["move3"], p["move4"]) if m],
        })
    return jsonify(battle=dict(battle), trainers=trainers)


# ---------------------------------------------------------------------------
# Attempts
# ---------------------------------------------------------------------------

@app.get("/api/attempts")
def list_attempts():
    rows = get_db().execute(
        "SELECT a.id, a.number, a.notes, a.created_at, "
        "       (SELECT COUNT(*) FROM catches c WHERE c.attempt_id = a.id) AS catch_count "
        "FROM attempts a ORDER BY a.number DESC"
    )
    return jsonify(attempts=[dict(r) for r in rows])


def parse_number(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ApiError("attempt number must be a non-negative integer")
    return value


@app.post("/api/attempts")
def create_attempt():
    conn = get_db()
    data = request.get_json(silent=True) or {}
    number = data.get("number")
    if number is None:
        number = conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM attempts").fetchone()[0]
    number = parse_number(number)
    try:
        with conn:
            cur = conn.execute("INSERT INTO attempts (number) VALUES (?)", (number,))
    except sqlite3.IntegrityError:
        raise ApiError(f"attempt {number} already exists", 409)
    return jsonify(attempt=dict(get_attempt(conn, cur.lastrowid))), 201


@app.patch("/api/attempts/<int:attempt_id>")
def update_attempt(attempt_id):
    conn = get_db()
    get_attempt(conn, attempt_id)
    data = body()
    try:
        with conn:
            if "number" in data:
                conn.execute("UPDATE attempts SET number = ? WHERE id = ?",
                             (parse_number(data["number"]), attempt_id))
            if "notes" in data:
                if not isinstance(data["notes"], str):
                    raise ApiError("notes must be a string")
                conn.execute("UPDATE attempts SET notes = ? WHERE id = ?",
                             (data["notes"], attempt_id))
    except sqlite3.IntegrityError:
        raise ApiError(f"attempt {data['number']} already exists", 409)
    return jsonify(attempt=dict(get_attempt(conn, attempt_id)))


@app.delete("/api/attempts/<int:attempt_id>")
def delete_attempt(attempt_id):
    conn = get_db()
    get_attempt(conn, attempt_id)
    with conn:
        conn.execute("DELETE FROM attempts WHERE id = ?", (attempt_id,))
    return "", 204


# ---------------------------------------------------------------------------
# Pokemon details: box Pokemon (catches) and battle-team copies share fields
# ---------------------------------------------------------------------------

MAX_TEXT = 40  # longest ability / item / move name accepted
DETAIL_FIELDS = {"species", "level", "ability", "nature", "item", "moves", "ivs", "status"}


def pokemon_json(row):
    return {
        "species": row["species"],
        "level": row["level"],
        "ability": row["ability"],
        "nature": row["nature"],
        "item": row["item"],
        "moves": [row[f"move{i}"] for i in range(1, 5)],
        "ivs": {stat: row[f"iv_{stat}"] for stat in db.IV_STATS},
        "status": row["status"],
    }


def catch_json(row):
    return {"id": row["id"], "route_id": row["route_id"], "pokemon": row["pokemon"], **pokemon_json(row)}


def member_json(row):
    return {"id": row["id"], "slot": row["slot"], "catch_id": row["catch_id"], **pokemon_json(row)}


def optional_int(value, name, low, high):
    if value is None or value == "":
        return None
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ApiError(f"{name} must be a whole number from {low} to {high}")
    return value


def optional_text(value, name):
    if value is None:
        return None
    if not isinstance(value, str) or len(value.strip()) > MAX_TEXT:
        raise ApiError(f"{name} must be text of at most {MAX_TEXT} characters")
    return value.strip() or None


def parse_details(conn, data):
    """Validate the Pokemon details in a request -> {column: value} for the fields sent."""
    unknown = set(data) - DETAIL_FIELDS
    if unknown:
        raise ApiError(f"unknown field(s): {', '.join(sorted(unknown))}")
    out = {}
    if "species" in data:
        species = data["species"]
        known = isinstance(species, str) and conn.execute(
            "SELECT 1 FROM species_sprites WHERE species = ?", (species,)).fetchone()
        if not known:
            raise ApiError("unknown species")
        out["species"] = species
    if "level" in data:
        out["level"] = optional_int(data["level"], "level", 1, 100)
    for field in ("ability", "item"):
        if field in data:
            out[field] = optional_text(data[field], field)
    if "nature" in data:
        nature = optional_text(data["nature"], "nature")
        if nature is not None and nature not in db.NATURES:
            raise ApiError(f"unknown nature {nature}")
        out["nature"] = nature
    if "moves" in data:
        moves = data["moves"]
        if not isinstance(moves, list) or len(moves) > 4:
            raise ApiError("moves must be a list of at most 4 names")
        moves = [optional_text(m, "move") for m in moves] + [None] * (4 - len(moves))
        out.update({f"move{i}": move for i, move in enumerate(moves, start=1)})
    if "ivs" in data:
        ivs = data["ivs"]
        if not isinstance(ivs, dict) or set(ivs) - set(db.IV_STATS):
            raise ApiError(f"ivs must be an object with keys {', '.join(db.IV_STATS)}")
        out.update({f"iv_{stat}": optional_int(value, f"{stat.upper()} IV", 0, 31)
                    for stat, value in ivs.items()})
    if "status" in data:
        if data["status"] not in db.STATUSES:
            raise ApiError(f"status must be one of {', '.join(db.STATUSES)}")
        out["status"] = data["status"]
    return out


def update_row(conn, table, row_id, fields):
    """UPDATE the given columns (names come from parse_details, never from the client)."""
    if fields:
        assignments = ", ".join(f"{column} = ?" for column in fields)
        conn.execute(f"UPDATE {table} SET {assignments} WHERE id = ?", (*fields.values(), row_id))


def fight_json(conn, fight_id):
    fight = conn.execute("SELECT id, battle_id, result FROM fights WHERE id = ?",
                         (fight_id,)).fetchone()
    members = [member_json(m) for m in conn.execute(
        "SELECT * FROM fight_members WHERE fight_id = ? ORDER BY slot", (fight_id,))]
    return dict(fight, members=members)


@app.get("/api/attempts/<int:attempt_id>")
def get_attempt_detail(attempt_id):
    conn = get_db()
    attempt = get_attempt(conn, attempt_id)
    catches = [catch_json(c) for c in conn.execute(
        "SELECT * FROM catches WHERE attempt_id = ?", (attempt_id,))]
    fights = [fight_json(conn, f["id"]) for f in conn.execute(
        "SELECT id FROM fights WHERE attempt_id = ?", (attempt_id,))]
    return jsonify(attempt=dict(attempt), catches=catches, fights=fights)


# ---------------------------------------------------------------------------
# Catches (the box): one per (attempt, route), restricted to the route's
# encounter table, with editable details
# ---------------------------------------------------------------------------

@app.put("/api/attempts/<int:attempt_id>/catches/<int:route_id>")
def set_catch(attempt_id, route_id):
    conn = get_db()
    get_attempt(conn, attempt_id)
    if conn.execute("SELECT 1 FROM routes WHERE id = ?", (route_id,)).fetchone() is None:
        raise ApiError("route not found", 404)
    pokemon = body().get("pokemon")

    if not pokemon:
        # Battle teams keep their copies of it (their catch_id becomes NULL).
        with conn:
            conn.execute("DELETE FROM catches WHERE attempt_id = ? AND route_id = ?",
                         (attempt_id, route_id))
        return jsonify(catch=None)

    allowed = conn.execute(
        "SELECT 1 FROM route_encounters WHERE route_id = ? AND pokemon = ?",
        (route_id, pokemon)).fetchone()
    if allowed is None:
        raise ApiError(f"{pokemon} cannot be encountered on this route")
    existing = conn.execute("SELECT id, pokemon FROM catches WHERE attempt_id = ? AND route_id = ?",
                            (attempt_id, route_id)).fetchone()
    with conn:
        if existing is None:
            conn.execute("INSERT INTO catches (attempt_id, route_id, pokemon, species) VALUES (?, ?, ?, ?)",
                         (attempt_id, route_id, pokemon, pokemon))
        elif existing["pokemon"] != pokemon:
            # A different catch on this route: its current form starts over as what was caught.
            conn.execute("UPDATE catches SET pokemon = ?, species = ? WHERE id = ?",
                         (pokemon, pokemon, existing["id"]))
    row = conn.execute("SELECT * FROM catches WHERE attempt_id = ? AND route_id = ?",
                       (attempt_id, route_id)).fetchone()
    return jsonify(catch=catch_json(row))


@app.patch("/api/catches/<int:catch_id>")
def update_catch(catch_id):
    """Edit a box Pokemon's details (including evolving it). Battle copies are unaffected."""
    conn = get_db()
    if conn.execute("SELECT 1 FROM catches WHERE id = ?", (catch_id,)).fetchone() is None:
        raise ApiError("catch not found", 404)
    fields = parse_details(conn, body())
    with conn:
        update_row(conn, "catches", catch_id, fields)
    return jsonify(catch=catch_json(conn.execute("SELECT * FROM catches WHERE id = ?", (catch_id,)).fetchone()))


# ---------------------------------------------------------------------------
# Fights: result + a team of up to six copies of box Pokemon
# ---------------------------------------------------------------------------

@app.put("/api/attempts/<int:attempt_id>/fights/<int:battle_id>")
def set_fight(attempt_id, battle_id):
    """Set a fight's result and team.

    `members` has up to six slots, each null (empty), {"id": n} to keep this
    fight's existing copy n in that slot, or {"catch_id": n} to add a fresh copy
    of box Pokemon n as it is now.
    """
    conn = get_db()
    get_attempt(conn, attempt_id)
    if conn.execute("SELECT 1 FROM battles WHERE id = ?", (battle_id,)).fetchone() is None:
        raise ApiError("battle not found", 404)
    data = body()

    result = data.get("result")
    if result not in RESULTS:
        raise ApiError("result must be 'won', 'lost' or null")

    members = data.get("members", [])
    if not isinstance(members, list) or len(members) > TEAM_SIZE:
        raise ApiError(f"members must be a list of at most {TEAM_SIZE} slots")
    fight = conn.execute("SELECT id FROM fights WHERE attempt_id = ? AND battle_id = ?",
                         (attempt_id, battle_id)).fetchone()
    existing = {} if fight is None else {m["id"]: m for m in conn.execute(
        "SELECT * FROM fight_members WHERE fight_id = ?", (fight["id"],))}

    kept, added = [], []
    for entry in members:
        if entry is None:
            continue
        key, value = next(iter(entry.items())) if isinstance(entry, dict) and len(entry) == 1 else (None, None)
        if isinstance(value, bool) or not isinstance(value, int) or key not in ("id", "catch_id"):
            raise ApiError('each team slot must be null, {"id": copy id} or {"catch_id": catch id}')
        if key == "id" and value not in existing:
            raise ApiError("that team member isn't in this fight")
        (kept if key == "id" else added).append(value)
    catch_ids = [existing[i]["catch_id"] for i in kept if existing[i]["catch_id"] is not None] + added
    if len(set(kept)) != len(kept) or len(set(catch_ids)) != len(catch_ids):
        raise ApiError("the same Pokemon can't fill two team slots")
    if added:
        placeholders = ",".join("?" * len(added))
        owned = conn.execute(
            f"SELECT COUNT(*) FROM catches WHERE attempt_id = ? AND id IN ({placeholders})",
            (attempt_id, *added)).fetchone()[0]
        if owned != len(added):
            raise ApiError("team members must be Pokemon caught during this attempt")

    columns = ", ".join(db.POKEMON_COLUMNS)
    with conn:
        if not kept and not added and result is None:
            conn.execute("DELETE FROM fights WHERE attempt_id = ? AND battle_id = ?",
                         (attempt_id, battle_id))
            return jsonify(fight=None)
        conn.execute(
            "INSERT INTO fights (attempt_id, battle_id, result) VALUES (?, ?, ?) "
            "ON CONFLICT (attempt_id, battle_id) DO UPDATE SET result = excluded.result",
            (attempt_id, battle_id, result))
        fight_id = conn.execute(
            "SELECT id FROM fights WHERE attempt_id = ? AND battle_id = ?",
            (attempt_id, battle_id)).fetchone()[0]
        # Rewrite the team: kept copies are re-inserted as they were (same id,
        # possibly a new slot), then added ones copy their box Pokemon's current
        # details. Kept copies go first so a new copy can never take a kept id.
        conn.execute("DELETE FROM fight_members WHERE fight_id = ?", (fight_id,))
        slots = [(slot, entry) for slot, entry in enumerate(members, start=1) if entry is not None]
        for slot, entry in slots:
            if "id" in entry:
                copy = existing[entry["id"]]
                conn.execute(
                    f"INSERT INTO fight_members (id, fight_id, slot, catch_id, {columns}) "
                    f"VALUES (?, ?, ?, ?, {','.join('?' * len(db.POKEMON_COLUMNS))})",
                    (copy["id"], fight_id, slot, copy["catch_id"], *(copy[c] for c in db.POKEMON_COLUMNS)))
        for slot, entry in slots:
            if "catch_id" in entry:
                conn.execute(
                    f"INSERT INTO fight_members (fight_id, slot, catch_id, {columns}) "
                    f"SELECT ?, ?, id, {columns} FROM catches WHERE id = ?",
                    (fight_id, slot, entry["catch_id"]))
    return jsonify(fight=fight_json(conn, fight_id))


@app.patch("/api/fight-members/<int:member_id>")
def update_member(member_id):
    """Edit one battle's copy of a Pokemon. The box Pokemon is unaffected."""
    conn = get_db()
    if conn.execute("SELECT 1 FROM fight_members WHERE id = ?", (member_id,)).fetchone() is None:
        raise ApiError("team member not found", 404)
    fields = parse_details(conn, body())
    with conn:
        update_row(conn, "fight_members", member_id, fields)
    row = conn.execute("SELECT * FROM fight_members WHERE id = ?", (member_id,)).fetchone()
    return jsonify(member=member_json(row))


def setup():
    conn = db.connect()
    try:
        db.init_db(conn)
    finally:
        conn.close()


setup()

if __name__ == "__main__":
    app.run(debug=True)
