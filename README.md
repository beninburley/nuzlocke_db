# Run & Bun Nuzlocke Tracker (MVP)

A small web app that replaces the user-entered parts of the Run & Bun master sheet:

- **Attempts**: pick which run you're on, or start a new one.
- **Encounters**: record what you caught on each route. The dropdown only offers
  Pokemon from that route's encounter table (from the sheet's *Encounters* tab).
- **Boss Fights**: record the team (up to 6) you brought to each of the 23 boss
  fights, plus won/lost. Slots only offer Pokemon caught during that attempt.
- **Notes**: free text per attempt.

Everything saves automatically on change.

## Setup (Windows / PowerShell)

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

## Run

```powershell
.venv\Scripts\python.exe app.py
```

Then open http://127.0.0.1:5000. The database (`instance/nuzlocke.db`) is
created on first start. Set `NUZLOCKE_DB` to use a different file.

## Data

**Game data** (routes, encounter tables, bosses and level caps, dupe-clause
evolution families) lives in `data/game_data.json`. It is extracted from the
spreadsheet and synced into the DB on every app start. If you edit the
spreadsheet's Encounters tab, re-extract it:

```powershell
.venv\Scripts\python.exe scripts\extract_game_data.py
```

**Past attempts** from the *Past Encounters* and *Past Boss Fights* tabs can be
imported (best effort):

```powershell
.venv\Scripts\python.exe scripts\import_history.py            # skips attempts already in the DB
.venv\Scripts\python.exe scripts\import_history.py --replace  # re-imports them
```

The import strips ability markers (`Lillipup-`), matches evolved or shorthand
names to catches through evolution families (`Grotle` -> the Turtwig starter,
`Zigzagoon` -> `Zigzagoon-G`), and fixes small typos. It puts "Killed:" rows and
free-text notes into each attempt's notes. It prints everything it corrected or
skipped.

To start over, stop the app and delete `instance/nuzlocke.db`.

## Rules enforced

Rules are checked in the API and again by SQLite triggers and constraints:

- one catch per route per attempt, and it must be in that route's encounter table
- a team member must be a catch from the same attempt, with no duplicates and at most 6
- clearing a route's catch removes it from any team; changing the species keeps it on the team

## Layout

```
app.py                 Flask app: JSON API + serves static/
db.py                  SQLite connection, schema setup, game-data sync
schema.sql             Tables and integrity triggers
data/game_data.json    Extracted game data
scripts/               Spreadsheet extraction and history import
static/                Frontend (plain HTML/CSS/JS, no build step)
```

### API

| Method | Path | Body |
|---|---|---|
| GET | `/api/game` | routes (with encounter options) and bosses |
| GET / POST | `/api/attempts` | `{number?}` |
| GET / PATCH / DELETE | `/api/attempts/<id>` | `{number?, notes?}` |
| PUT | `/api/attempts/<id>/catches/<route_id>` | `{pokemon}` (null clears) |
| PUT | `/api/attempts/<id>/fights/<boss_id>` | `{members: [catch_id or null] x6, result: "won" or "lost" or null}` |

## Not in the MVP yet

- Per-Pokemon details: evolved form at each fight, nature/ability, death (who killed it)
- Failed or skipped encounters (a `-` in the old sheet)
- Dupes-clause warnings (the family data is already in the DB)
- User accounts (it's single-user right now)
- UI/UX polish
