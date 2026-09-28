# Run & Bun Nuzlocke Tracker (MVP)

A small web app that replaces the user-entered parts of the Run & Bun master sheet:

- **Attempts**: pick which run you're on, or start a new one.
- **Encounters**: record what you caught on each route. *+ Add catch* only
  offers Pokemon from that route's encounter table (from the sheet's
  *Encounters* tab). Picking one opens a details popup; fill it in, or *Skip*
  and do it later on the Box tab.
- **Box**: every Pokemon caught this attempt, on the right. The selected one's
  details are on the left: level, status (OK / Burn / Sleep / Fainted),
  nature, ability, held item, four moves and IVs. Ability, item and move boxes
  suggest the names Run & Bun's trainers use. *Evolve…* shows the whole
  evolutionary line (from PokeAPI) and evolves or devolves in one click.
- **Trainer Battles**: the slide-out list has one dropdown per split, e.g.
  "Route 104 Aqua Grunt Split". Each lists that split's trainers in game order,
  ending with the level-cap boss. You can also type in the filter box. Pick
  any trainer to see their team: each Pokemon's level, held item, ability,
  nature and moves. Fights with several trainers get a switcher: the rival's
  starter variants, Museum grunts #1/#2, Tate & Liza, and tag-battle partners.
  Drag Pokemon from your box (only this attempt's catches) into the six team
  slots. You can also click a box Pokemon to add or remove it. Drag between
  slots to swap, or back to the box to remove. Mark each fight won or lost.
  A team stores **copies**: adding a Pokemon copies it as it is right then, so
  evolving or editing it in the Box later doesn't rewrite past fights (and
  editing a copy doesn't touch the box). Click a team member to see or edit
  that fight's copy. If any copy differs from the box, the fight shows *This
  fight used Pokémon that have since been changed*.
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

## Deploying (PythonAnywhere, free)

The live site runs on a free PythonAnywhere "Beginner" account. That plan
keeps the SQLite database on a persistent disk, serves HTTPS at
`<username>.pythonanywhere.com`, and has built-in password protection.

First-time setup:

1. On the **Web** tab, *Add a new web app* → *Manual configuration* → *Python 3.11*.
2. Open a **Bash console** and run:

   ```bash
   git clone https://github.com/beninburley/nuzlocke_db.git ~/nuzlocke_db
   bash ~/nuzlocke_db/deploy/pythonanywhere_setup.sh
   ```

3. Back on the **Web** tab, set *Source code* to `/home/<username>/nuzlocke_db` and
   *Virtualenv* to `/home/<username>/.virtualenvs/nuzlocke`. Turn on **Force HTTPS**
   and **Password protection**. The app has no login of its own, so without
   password protection anyone with the URL could edit your data. Click **Reload**.
4. To bring your existing data along, upload your local `instance/nuzlocke.db` on
   the **Files** tab into `/home/<username>/nuzlocke_db/instance/`, replacing the
   file there. Then click **Reload**. From then on, the live site's database is the
   one to use.

To deploy an update after merging to `main`, re-run the setup script in a Bash
console. It pulls, installs dependencies and reloads the site.

Free web apps must be renewed monthly: click *Run until 1 month from today* on
the **Web** tab, or the site gets disabled.

## Data

**Game data** lives in `data/game_data.json`. It is extracted from the
spreadsheet and synced into the DB on every app start. It covers:

- routes and encounter tables (*Encounters* tab)
- every trainer and their team (*Trainer Lookup* tab, the data behind the
  *Trainers* tab)
- the level-cap fights (*Past Boss Fights* header)
- dupe-clause evolution families

Level-cap fights are matched to their trainers by `LEVEL_CAP_TRAINERS` in
`scripts/extract_game_data.py`. If you edit the spreadsheet, re-extract:

```powershell
.venv\Scripts\python.exe scripts\extract_game_data.py
```

**Sprites** come from [PokeAPI](https://pokeapi.co/). `data/sprites.json` maps
every species in the game data to its PokeAPI sprite URL, so the app never calls
the API itself. Spreadsheet names are translated along the way (`Zigzagoon-G` ->
`zigzagoon-galar`, `Deerling-A` -> `deerling-autumn`). Re-run the script after
re-extracting game data if new species appear:

```powershell
.venv\Scripts\python.exe scripts\fetch_sprites.py
```

**Evolution lines** come from PokeAPI's evolution chains, cached in
`data/evolutions.json`. Regional forms keep their line (Growlithe-H ->
Arcanine-H). Re-run after re-extracting game data:

```powershell
.venv\Scripts\python.exe scripts\fetch_evolutions.py
```

**Past attempts** from the *Past Encounters* and *Past Boss Fights* tabs can be
imported (best effort):

```powershell
.venv\Scripts\python.exe scripts\import_history.py            # skips attempts already in the DB
.venv\Scripts\python.exe scripts\import_history.py --replace  # re-imports them
```

The import strips ability markers (`Lillipup-`), matches evolved or shorthand
names to catches through evolution families (`Grotle` -> the Turtwig starter,
`Zigzagoon` -> `Zigzagoon-G`), and fixes small typos. Battle copies get the
form the sheet lists for that fight, and each box Pokemon gets the latest form
it reached. It puts "Killed:" rows and free-text notes into each attempt's
notes. It prints everything it corrected or skipped.

Databases imported before battle copies existed can get those forms
afterwards. The script only changes copies and box Pokemon still showing their
caught species, so edits made in the app are kept:

```powershell
.venv\Scripts\python.exe scripts\backfill_forms.py --dry-run   # show what would change
.venv\Scripts\python.exe scripts\backfill_forms.py
```

To start over, stop the app and delete `instance/nuzlocke.db`.

When a new version changes the schema, the app migrates the existing database
on startup. It first saves a copy next to it (e.g. `nuzlocke.backup-v1.db`).

## Rules enforced

Rules are checked in the API and again by SQLite triggers and constraints:

- one catch per route per attempt, and what was caught must be in that route's encounter table
  (its current species can then evolve freely)
- level 1-100, IVs 0-31, status one of OK / Burn / Sleep / Fainted, nature one of the 25
- a team member must be a copy of a catch from the same attempt, with no duplicates and at most 6
- removing a route's catch keeps the battle copies made from it (they show as "no longer in box");
  changing the Pokemon caught on a route resets its current species

## Layout

```
app.py                 Flask app: JSON API + serves static/
db.py                  SQLite connection, schema setup, game-data sync
schema.sql             Tables and integrity triggers
data/game_data.json    Extracted game data
data/sprites.json      Species -> PokeAPI sprite URL
data/evolutions.json   Species -> its evolutionary line (PokeAPI)
scripts/               Spreadsheet extraction, PokeAPI lookups, history import/backfill
static/                Frontend (plain HTML/CSS/JS, no build step)
```

### API

| Method | Path | Body |
|---|---|---|
| GET | `/api/game` | routes (with encounter options), battles, sprites, evolution lines, natures, statuses, suggestions |
| GET | `/api/battles/<id>` | a battle's trainers and their teams |
| GET / POST | `/api/attempts` | `{number?}` |
| GET / PATCH / DELETE | `/api/attempts/<id>` | `{number?, notes?}` |
| PUT | `/api/attempts/<id>/catches/<route_id>` | `{pokemon}` (null clears) |
| PATCH | `/api/catches/<id>` | any of `{species, level, ability, nature, item, moves: [4], ivs: {hp, atk, def, spa, spd, spe}, status}` |
| PUT | `/api/attempts/<id>/fights/<battle_id>` | `{members: [slot] x6, result: "won" or "lost" or null}`; each slot is `null`, `{"id": copy}` (keep) or `{"catch_id": n}` (new copy) |
| PATCH | `/api/fight-members/<id>` | same fields as a catch; edits that battle's copy only |

## Not in the MVP yet

- Trainer portraits (the sheet's *Sprites* tab embeds images rather than linking them)
- Tracking which trainers you've beaten or skipped (the *Trainers* tab's Status column)
- Who killed a Pokemon (the old sheet's "Killed:" rows are only in each attempt's notes)
- Failed or skipped encounters (a `-` in the old sheet)
- Dupes-clause warnings (the family data is already in the DB)
- User accounts (it's single-user right now)
- UI/UX polish
