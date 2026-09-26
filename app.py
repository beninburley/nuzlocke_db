"""Nuzlocke tracker: JSON API + static frontend.

Run with:  python app.py   (then open http://127.0.0.1:5000)
"""
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
    return jsonify(routes=routes, battles=battles, sprites=sprites)


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


def fight_json(conn, fight_id):
    fight = conn.execute("SELECT id, battle_id, result FROM fights WHERE id = ?",
                         (fight_id,)).fetchone()
    members = [dict(m) for m in conn.execute(
        "SELECT slot, catch_id FROM fight_members WHERE fight_id = ? ORDER BY slot",
        (fight_id,))]
    return dict(fight, members=members)


@app.get("/api/attempts/<int:attempt_id>")
def get_attempt_detail(attempt_id):
    conn = get_db()
    attempt = get_attempt(conn, attempt_id)
    catches = [dict(c) for c in conn.execute(
        "SELECT id, route_id, pokemon FROM catches WHERE attempt_id = ?", (attempt_id,))]
    fights = [fight_json(conn, f["id"]) for f in conn.execute(
        "SELECT id FROM fights WHERE attempt_id = ?", (attempt_id,))]
    return jsonify(attempt=dict(attempt), catches=catches, fights=fights)


# ---------------------------------------------------------------------------
# Catches: one per (attempt, route), restricted to the route's encounter table
# ---------------------------------------------------------------------------

@app.put("/api/attempts/<int:attempt_id>/catches/<int:route_id>")
def set_catch(attempt_id, route_id):
    conn = get_db()
    get_attempt(conn, attempt_id)
    if conn.execute("SELECT 1 FROM routes WHERE id = ?", (route_id,)).fetchone() is None:
        raise ApiError("route not found", 404)
    pokemon = body().get("pokemon")

    if not pokemon:
        with conn:
            conn.execute("DELETE FROM catches WHERE attempt_id = ? AND route_id = ?",
                         (attempt_id, route_id))
        return jsonify(catch=None)

    allowed = conn.execute(
        "SELECT 1 FROM route_encounters WHERE route_id = ? AND pokemon = ?",
        (route_id, pokemon)).fetchone()
    if allowed is None:
        raise ApiError(f"{pokemon} cannot be encountered on this route")
    # Upsert keeps the catch id stable, so teams that include it follow the change.
    with conn:
        conn.execute(
            "INSERT INTO catches (attempt_id, route_id, pokemon) VALUES (?, ?, ?) "
            "ON CONFLICT (attempt_id, route_id) DO UPDATE SET pokemon = excluded.pokemon",
            (attempt_id, route_id, pokemon))
    row = conn.execute(
        "SELECT id, route_id, pokemon FROM catches WHERE attempt_id = ? AND route_id = ?",
        (attempt_id, route_id)).fetchone()
    return jsonify(catch=dict(row))


# ---------------------------------------------------------------------------
# Fights: result + team of up to six catches from the same attempt
# ---------------------------------------------------------------------------

@app.put("/api/attempts/<int:attempt_id>/fights/<int:battle_id>")
def set_fight(attempt_id, battle_id):
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
        raise ApiError(f"members must be a list of at most {TEAM_SIZE} catch ids")
    chosen = [m for m in members if m is not None]
    if any(isinstance(m, bool) or not isinstance(m, int) for m in chosen):
        raise ApiError("members must be catch ids or null")
    if len(set(chosen)) != len(chosen):
        raise ApiError("the same Pokemon can't fill two team slots")
    if chosen:
        placeholders = ",".join("?" * len(chosen))
        owned = conn.execute(
            f"SELECT COUNT(*) FROM catches WHERE attempt_id = ? AND id IN ({placeholders})",
            (attempt_id, *chosen)).fetchone()[0]
        if owned != len(chosen):
            raise ApiError("team members must be Pokemon caught during this attempt")

    with conn:
        if not chosen and result is None:
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
        conn.execute("DELETE FROM fight_members WHERE fight_id = ?", (fight_id,))
        conn.executemany(
            "INSERT INTO fight_members (fight_id, slot, catch_id) VALUES (?, ?, ?)",
            [(fight_id, slot, catch_id)
             for slot, catch_id in enumerate(members, start=1) if catch_id is not None])
    return jsonify(fight=fight_json(conn, fight_id))


def setup():
    conn = db.connect()
    try:
        db.init_db(conn)
    finally:
        conn.close()


setup()

if __name__ == "__main__":
    app.run(debug=True)
