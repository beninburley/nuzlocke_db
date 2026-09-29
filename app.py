"""Nuzlocke tracker: JSON API + static frontend, with accounts.

Run with:  python app.py   (then open http://127.0.0.1:5000)
"""
import json
import os
import sqlite3
from datetime import timedelta

from flask import Flask, g, jsonify, redirect, request, session

import accounts
import box_script
import db

app = Flask(__name__, static_folder="static", static_url_path="")
app.config.update(
    SECRET_KEY=accounts.load_secret_key(db.DB_PATH.parent / "secret_key"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    # The live site is HTTPS-only; its WSGI file sets this so the login
    # cookie is never sent over plain HTTP.
    SESSION_COOKIE_SECURE=os.environ.get("NUZLOCKE_SECURE_COOKIES") == "1",
    PERMANENT_SESSION_LIFETIME=timedelta(days=30),
)
failed_logins = accounts.RateLimit(limit=10, window=15 * 60)
signups = accounts.RateLimit(limit=5, window=60 * 60)

TEAM_SIZE = 6
RESULTS = (None, "won", "lost")
KO_BY = ("player", "enemy")


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
    """One of the logged-in user's attempts (other users' attempts are 'not found')."""
    row = conn.execute("SELECT * FROM attempts WHERE id = ? AND user_id = ?",
                       (attempt_id, user_id())).fetchone()
    if row is None:
        raise ApiError("attempt not found", 404)
    return row


# ---------------------------------------------------------------------------
# Accounts and sessions
# ---------------------------------------------------------------------------

# API endpoints anyone may call. Every other /api/ endpoint needs a login, and
# only ever sees the logged-in user's own data.
PUBLIC_API = {"signup", "login", "logout", "me"}


def current_user():
    """The logged-in user's row, or None."""
    if "user" not in g:
        g.user = None
        if "user_id" in session:
            row = get_db().execute("SELECT * FROM users WHERE id = ?", (session["user_id"],)).fetchone()
            # Sessions from before a password change or "log out everywhere" are void.
            if row and row["password_hash"] and row["session_epoch"] == session.get("epoch"):
                g.user = row
    return g.user


def user_id():
    return current_user()["id"]


@app.before_request
def check_api_request():
    if not request.path.startswith("/api/"):
        return
    # Other sites can't make a browser send a custom header to this one (that
    # would need a CORS preflight, which this app never grants), so requiring
    # it on every change stops cross-site request forgery.
    if request.method not in ("GET", "HEAD", "OPTIONS") and not request.headers.get("X-Requested-With"):
        raise ApiError("missing X-Requested-With header", 403)
    if request.endpoint not in PUBLIC_API and current_user() is None:
        raise ApiError("log in first", 401)


def start_session(user):
    session.clear()
    session.permanent = True
    session["user_id"] = user["id"]
    session["epoch"] = user["session_epoch"]
    g.pop("user", None)


def client_address():
    # PythonAnywhere's proxy passes the visitor's own address in X-Real-IP.
    return request.headers.get("X-Real-IP") or request.remote_addr or "unknown"


def user_json(conn, user):
    attempts = conn.execute("SELECT COUNT(*) FROM attempts WHERE user_id = ?", (user["id"],)).fetchone()[0]
    return {"username": user["username"], "role": user["role"],
            "created_at": user["created_at"], "attempts": attempts}


def credentials():
    data = body()
    username, password = data.get("username"), data.get("password")
    return (username.strip() if isinstance(username, str) else username), password


def wait_message(seconds, what):
    minutes = -(-seconds // 60)
    return f"Too many {what}. Try again in {minutes} minute{'s' if minutes != 1 else ''}."


@app.post("/api/signup")
def signup():
    """Create an account (role: trainer) and log in to it."""
    address = client_address()
    wait = signups.retry_after(address)
    if wait:
        raise ApiError(wait_message(wait, "new accounts from here"), 429)
    username, password = credentials()
    problem = accounts.username_problem(username) or accounts.password_problem(password)
    if problem:
        raise ApiError(problem)
    conn = get_db()
    try:
        with conn:
            cur = conn.execute("INSERT INTO users (username, password_hash, role) VALUES (?, ?, ?)",
                               (username, accounts.hash_password(password), accounts.DEFAULT_ROLE))
    except sqlite3.IntegrityError:
        raise ApiError("That username is taken.", 409)
    signups.record(address)
    user = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
    start_session(user)
    return jsonify(user=user_json(conn, user)), 201


@app.post("/api/login")
def login():
    address = client_address()
    wait = failed_logins.retry_after(address)
    if wait:
        raise ApiError(wait_message(wait, "failed logins"), 429)
    username, password = credentials()
    conn = get_db()
    user = None
    if isinstance(username, str) and isinstance(password, str) and len(password) <= accounts.MAX_PASSWORD:
        user = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        ok = accounts.verify_password(user["password_hash"] if user else None, password)
    else:
        ok = False
    if not ok:
        failed_logins.record(address)
        raise ApiError("Wrong username or password.", 401)
    failed_logins.clear(address)
    start_session(user)
    return jsonify(user=user_json(conn, user))


@app.post("/api/logout")
def logout():
    session.clear()
    return "", 204


@app.get("/api/me")
def me():
    """The logged-in user, or null (never a 401, so pages can ask freely)."""
    user = current_user()
    return jsonify(user=None if user is None else user_json(get_db(), user))


@app.post("/api/me/password")
def change_password():
    """Change the password. Every other session of this account is logged out."""
    address = client_address()
    wait = failed_logins.retry_after(address)
    if wait:
        raise ApiError(wait_message(wait, "wrong passwords"), 429)
    data = body()
    current, new = data.get("current_password"), data.get("new_password")
    user = current_user()
    if (not isinstance(current, str) or len(current) > accounts.MAX_PASSWORD
            or not accounts.verify_password(user["password_hash"], current)):
        failed_logins.record(address)
        raise ApiError("Your current password is wrong.", 403)
    problem = accounts.password_problem(new)
    if problem:
        raise ApiError(problem)
    conn = get_db()
    with conn:
        conn.execute("UPDATE users SET password_hash = ?, session_epoch = session_epoch + 1 WHERE id = ?",
                     (accounts.hash_password(new), user["id"]))
    user = conn.execute("SELECT * FROM users WHERE id = ?", (user["id"],)).fetchone()
    start_session(user)  # this session carries on with the new epoch
    return jsonify(user=user_json(conn, user))


@app.post("/api/me/logout-everywhere")
def logout_everywhere():
    """End every session of this account, on every device (this one too)."""
    conn = get_db()
    with conn:
        conn.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (user_id(),))
    session.clear()
    return "", 204


# ---------------------------------------------------------------------------
# Pages
# ---------------------------------------------------------------------------

@app.get("/")
def landing():
    return app.send_static_file("landing.html")


@app.get("/login")
def login_page():
    if current_user() is not None:
        return redirect("/app")
    return app.send_static_file("login.html")


@app.get("/app")
def tracker_page():
    if current_user() is None:
        return redirect("/login?next=/app")
    return app.send_static_file("index.html")


@app.get("/account")
def account_page():
    if current_user() is None:
        return redirect("/login?next=/account")
    return app.send_static_file("account.html")


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
        "SELECT id, name, location, level_cap, group_id, split FROM battles ORDER BY position")]
    by_battle = {b["id"]: b for b in battles}
    for trainer in conn.execute("SELECT battle_id, tags FROM trainers ORDER BY position"):
        tags = by_battle[trainer["battle_id"]]["tags"]
        tags.extend(t for t in trainer["tags"].split(",") if t and t not in tags)
    sprites = {r["species"]: r["url"] for r in conn.execute("SELECT species, url FROM species_sprites")}
    evolutions = evolution_lines(conn)
    families = species_families(conn)
    # Autocomplete for box Pokemon details: the names Run & Bun's own trainers use.
    distinct = lambda sql: [r[0] for r in conn.execute(sql)]  # noqa: E731
    suggestions = {
        "abilities": distinct("SELECT DISTINCT ability FROM trainer_pokemon WHERE ability IS NOT NULL ORDER BY 1"),
        "items": distinct("SELECT DISTINCT item FROM trainer_pokemon WHERE item IS NOT NULL ORDER BY 1"),
        "moves": distinct(" UNION ".join(
            f"SELECT move{i} FROM trainer_pokemon WHERE move{i} IS NOT NULL" for i in range(1, 5)) + " ORDER BY 1"),
    }
    return jsonify(routes=routes, battles=battles, sprites=sprites, evolutions=evolutions, families=families,
                   suggestions=suggestions, natures=db.NATURES, statuses=db.STATUSES, iv_stats=db.IV_STATS)


def evolution_lines(conn):
    """species -> its evolutionary line (PokeAPI)."""
    return {r["species"]: json.loads(r["members"]) for r in conn.execute("SELECT species, members FROM evolution_lines")}


def species_families(conn):
    """species -> dupes-clause family id (evolution lines plus regional forms, from the sheet)."""
    return {r["species"]: r["family_id"] for r in conn.execute("SELECT species, family_id FROM species_families")}


@app.get("/api/battles/<int:battle_id>")
def battle_detail(battle_id):
    """A battle's trainers and their full teams (item, ability, nature, moves)."""
    conn = get_db()
    battle = conn.execute(
        "SELECT id, name, location, level_cap, group_id, split FROM battles WHERE id = ?",
        (battle_id,)).fetchone()
    if battle is None:
        raise ApiError("battle not found", 404)
    trainers = [dict(t, tags=[x for x in t["tags"].split(",") if x], pokemon=[])
                for t in conn.execute(
                    "SELECT id, key, name, location, tags FROM trainers "
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
        "FROM attempts a WHERE a.user_id = ? ORDER BY a.number DESC", (user_id(),)
    )
    return jsonify(attempts=[dict(r) for r in rows])


def attempt_json(row):
    return {"id": row["id"], "number": row["number"], "notes": row["notes"], "created_at": row["created_at"]}


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
        number = conn.execute("SELECT COALESCE(MAX(number), 0) + 1 FROM attempts WHERE user_id = ?",
                              (user_id(),)).fetchone()[0]
    number = parse_number(number)
    try:
        with conn:
            cur = conn.execute("INSERT INTO attempts (user_id, number) VALUES (?, ?)", (user_id(), number))
    except sqlite3.IntegrityError:
        raise ApiError(f"attempt {number} already exists", 409)
    return jsonify(attempt=attempt_json(get_attempt(conn, cur.lastrowid))), 201


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
    return jsonify(attempt=attempt_json(get_attempt(conn, attempt_id)))


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
    fight = conn.execute("SELECT id, battle_id, result, trainer_key FROM fights WHERE id = ?",
                         (fight_id,)).fetchone()
    members = [member_json(m) for m in conn.execute(
        "SELECT * FROM fight_members WHERE fight_id = ? ORDER BY slot", (fight_id,))]
    kos = [{"member": k["member_id"], "enemy": k["enemy_slot"], "by": k["ko_by"]} for k in conn.execute(
        "SELECT member_id, enemy_slot, ko_by FROM fight_kos WHERE fight_id = ? ORDER BY id", (fight_id,))]
    return {"id": fight["id"], "battle_id": fight["battle_id"], "result": fight["result"],
            "trainer": fight["trainer_key"], "members": members, "kos": kos}


@app.get("/api/attempts/<int:attempt_id>")
def get_attempt_detail(attempt_id):
    conn = get_db()
    attempt = get_attempt(conn, attempt_id)
    catches = [catch_json(c) for c in conn.execute(
        "SELECT * FROM catches WHERE attempt_id = ?", (attempt_id,))]
    fights = [fight_json(conn, f["id"]) for f in conn.execute(
        "SELECT id FROM fights WHERE attempt_id = ?", (attempt_id,))]
    return jsonify(attempt=attempt_json(attempt), catches=catches, fights=fights)


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
    owned = conn.execute("SELECT 1 FROM catches c JOIN attempts a ON a.id = c.attempt_id "
                         "WHERE c.id = ? AND a.user_id = ?", (catch_id, user_id())).fetchone()
    if owned is None:
        raise ApiError("catch not found", 404)
    fields = parse_details(conn, body())
    with conn:
        update_row(conn, "catches", catch_id, fields)
    return jsonify(catch=catch_json(conn.execute("SELECT * FROM catches WHERE id = ?", (catch_id,)).fetchone()))


@app.post("/api/attempts/<int:attempt_id>/box-script")
def run_box_script(attempt_id):
    """Update box Pokemon from a Showdown-style script (see box_script.py).

    Body: {"script": text, "apply": bool}. Without "apply" it's a preview: each
    set's matching box Pokemon and the changes it would make, or why it can't
    be used. With "apply": true, every usable set with changes is saved (all
    at once) and the updated box Pokemon come back as "catches".
    """
    conn = get_db()
    get_attempt(conn, attempt_id)
    data = body()
    script, apply = data.get("script"), data.get("apply", False)
    if not isinstance(script, str) or len(script) > box_script.MAX_SCRIPT:
        raise ApiError(f"script must be text of at most {box_script.MAX_SCRIPT} characters")
    if not isinstance(apply, bool):
        raise ApiError("apply must be true or false")

    box = conn.execute(
        "SELECT c.*, r.name AS route FROM catches c JOIN routes r ON r.id = c.route_id "
        "WHERE c.attempt_id = ? ORDER BY r.position", (attempt_id,)).fetchall()
    lines, families = evolution_lines(conn), species_families(conn)
    results, updates, taken = [], {}, {}
    for s in box_script.parse(script):
        result = {"line": s.line, "name": s.name, "ignored": s.ignored, "problem": s.problem, "changes": []}
        results.append(result)
        if s.problem:
            continue
        mon, species, problem = box_script.match(s.name, box, lines, families, taken)
        if mon is None:
            # A Pokemon an earlier set already updated? Say so rather than "not in your box".
            again, _, _ = box_script.match(s.name, box, lines, families)
            result["problem"] = (f"Line {taken[again['id']]} already updates this {again['species']} "
                                 f"({again['route']}).") if again and again["id"] in taken else problem
            continue
        taken[mon["id"]] = s.line
        result.update(catch_id=mon["id"], species=mon["species"], route=mon["route"], becomes=species)
        try:
            fields = parse_details(conn, {**s.details, "species": species})
        except ApiError as err:
            result["problem"] = f"{s.name}: {err.message}"
            continue
        result["changes"] = detail_changes(mon, fields)
        if result["changes"]:
            updates[mon["id"]] = fields

    catches = []
    if apply and updates:
        with conn:
            for catch_id, fields in updates.items():
                update_row(conn, "catches", catch_id, fields)
        catches = [catch_json(r) for r in conn.execute(
            f"SELECT * FROM catches WHERE id IN ({','.join('?' * len(updates))})", tuple(updates))]
    return jsonify(sets=results, applied=bool(apply and updates), catches=catches)


def detail_changes(row, fields):
    """What saving `fields` (columns, from parse_details) would change on `row`, for the preview."""
    changes = [{"field": key, "from": row[key], "to": fields[key]}
               for key in ("species", "level", "ability", "nature", "item")
               if key in fields and fields[key] != row[key]]
    if "move1" in fields:
        old, new = ([source[f"move{i}"] for i in range(1, 5)] for source in (row, fields))
        if old != new:
            changes.append({"field": "moves", "from": old, "to": new})
    if any(f"iv_{stat}" in fields for stat in db.IV_STATS):
        old = {stat: row[f"iv_{stat}"] for stat in db.IV_STATS}
        new = {stat: fields.get(f"iv_{stat}", old[stat]) for stat in db.IV_STATS}
        if old != new:
            changes.append({"field": "ivs", "from": old, "to": new})
    return changes


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
        # Deleting the copies deletes their KOs too, so those of kept copies
        # are put back afterwards.
        kos = conn.execute("SELECT member_id, enemy_slot, ko_by FROM fight_kos WHERE fight_id = ?",
                           (fight_id,)).fetchall()
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
        conn.executemany(
            "INSERT INTO fight_kos (fight_id, member_id, enemy_slot, ko_by) VALUES (?, ?, ?, ?)",
            [(fight_id, *ko) for ko in kos if ko["member_id"] in kept])
    return jsonify(fight=fight_json(conn, fight_id))


@app.put("/api/fights/<int:fight_id>/kos")
def set_kos(fight_id):
    """Replace a fight's KOs (the KO tracker's arrows).

    Body: {"trainer": key or null, "kos": [{"member": copy id, "enemy": slot,
    "by": "player" or "enemy"}]}. "trainer" is the enemy team fought, for
    battles with alternative teams (null = the first). "by": "player" means
    the team member knocked out the enemy Pokemon in that slot; "enemy" means
    the enemy Pokemon knocked out the team member.
    """
    conn = get_db()
    fight = conn.execute("SELECT f.id, f.battle_id FROM fights f JOIN attempts a ON a.id = f.attempt_id "
                         "WHERE f.id = ? AND a.user_id = ?", (fight_id, user_id())).fetchone()
    if fight is None:
        raise ApiError("fight not found", 404)
    data = body()
    unknown = set(data) - {"trainer", "kos"}
    if unknown:
        raise ApiError(f"unknown field(s): {', '.join(sorted(unknown))}")

    enemies = conn.execute(
        "SELECT id, key FROM trainers WHERE battle_id = ? AND ',' || tags || ',' NOT LIKE '%,Tag Partner,%' "
        "ORDER BY position", (fight["battle_id"],)).fetchall()
    trainer_key = data.get("trainer")
    if trainer_key is not None and trainer_key not in {t["key"] for t in enemies}:
        raise ApiError("trainer is not an enemy in this battle")
    trainer = next((t for t in enemies if t["key"] == trainer_key), enemies[0] if enemies else None)
    team_size = 0 if trainer is None else conn.execute(
        "SELECT COUNT(*) FROM trainer_pokemon WHERE trainer_id = ?", (trainer["id"],)).fetchone()[0]
    members = {m["id"] for m in conn.execute("SELECT id FROM fight_members WHERE fight_id = ?", (fight_id,))}

    kos = data.get("kos", [])
    if not isinstance(kos, list):
        raise ApiError("kos must be a list")
    rows = []
    for ko in kos:
        if not isinstance(ko, dict) or set(ko) != {"member", "enemy", "by"}:
            raise ApiError('each KO must be {"member": copy id, "enemy": slot, "by": "player" or "enemy"}')
        member, enemy, by = ko["member"], ko["enemy"], ko["by"]
        if isinstance(member, bool) or not isinstance(member, int) or member not in members:
            raise ApiError("KO team member isn't in this fight")
        if isinstance(enemy, bool) or not isinstance(enemy, int) or not 1 <= enemy <= team_size:
            raise ApiError(f"enemy must be a slot from 1 to {team_size}")
        if by not in KO_BY:
            raise ApiError("by must be 'player' or 'enemy'")
        rows.append((member, enemy, by))
    knocked_out = [("enemy", enemy) if by == "player" else ("member", member) for member, enemy, by in rows]
    if len(set(knocked_out)) != len(knocked_out):
        raise ApiError("a Pokemon can only be knocked out once per fight")

    with conn:
        conn.execute("UPDATE fights SET trainer_key = ? WHERE id = ?", (trainer_key, fight_id))
        conn.execute("DELETE FROM fight_kos WHERE fight_id = ?", (fight_id,))
        conn.executemany("INSERT INTO fight_kos (fight_id, member_id, enemy_slot, ko_by) VALUES (?, ?, ?, ?)",
                         [(fight_id, *row) for row in rows])
    return jsonify(fight=fight_json(conn, fight_id))


@app.patch("/api/fight-members/<int:member_id>")
def update_member(member_id):
    """Edit one battle's copy of a Pokemon. The box Pokemon is unaffected."""
    conn = get_db()
    owned = conn.execute("SELECT 1 FROM fight_members m JOIN fights f ON f.id = m.fight_id "
                         "JOIN attempts a ON a.id = f.attempt_id WHERE m.id = ? AND a.user_id = ?",
                         (member_id, user_id())).fetchone()
    if owned is None:
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
