# Run & Bun Nuzlocke Tracker (MVP)

A small web app that replaces the user-entered parts of the Run & Bun master sheet,
for anyone who makes an account:

- **Accounts**: the landing page (`/`) explains the site and links to log in or
  create an account (`/login`). Each account sees and edits only its own
  attempts. The account button (top right) shows who's logged in and links to
  the account page (`/account`), where you can see your details, change your
  password and log out (here or everywhere). Every account has a role:
  sign-ups are *trainers*; the others are *mod*, *content creator* and
  *admin*. Only admins get anything extra so far: the admin page.
- **Admin** (admins only: the *Admin* button next to the account button,
  `/admin`): a home page with three sections.
  - *Roles*: every account, with its role as a drop-down that saves on
    change. You can't change your own role, so there's always an admin.
  - *Trainer Battles*: pick a battle to see its enemy team, laid out as on
    the Trainer Battles tab, and *Edit* it in a popup (species, level, item,
    ability, nature and moves of each Pokemon; blank a species to remove
    one). Game data is reloaded from `data/game_data.json` on every start, so
    corrections are kept in a table of their own (`trainer_edits`) and
    applied again after each reload. The battle shows who corrected it and
    when, and can be reverted to the spreadsheet's team.
  - *Verification Requests*: not built yet ("Work in Process").
- **Attempts**: pick which run you're on, or start a new one. Each attempt
  in the list shows the split it's on: the one with its first boss it hasn't
  beaten, marked "(lost)" if that's where the run ended.
- **Encounters**: record what you caught on each route. *+ Add catch* only
  offers Pokemon from that route's encounter table (from the sheet's
  *Encounters* tab). Picking one opens a details popup; fill it in, or *Skip*
  and do it later on the Box tab. **Dupes clause**: a Pokemon in the same
  family as one you've already caught (its evolutionary line, or a family in
  the sheet's dupes table, which includes regional forms) is greyed out, and
  the odds of the rest are scaled up to add to 100%. You can still record a
  dupe after confirming. Routes you haven't caught on yet show *Dupes
  contained* if their pool has any.
- **Box**: every Pokemon caught this attempt, on the right. The selected one's
  details are on the left: level, status (OK / Burn / Sleep / Fainted),
  nature, ability, held item, four moves and IVs. Ability, item and move boxes
  suggest the names Run & Bun's trainers use. *Evolve…* shows the whole
  evolutionary line (from PokeAPI) and evolves or devolves in one click.
  Fainted Pokemon are greyed out with a "Fainted" stamp, here and on the
  Trainer Battles tab.
- **Update - Script** (beside *Box* on the Box and Trainer Battles tabs):
  paste Showdown-style sets to update box Pokemon in bulk. Each set updates
  the Pokemon of that species or its evolutionary line, evolving it if the
  set names another stage. It never adds Pokemon. The popup previews every
  change as you type, and *Update* saves them. Anything a set leaves out stays
  as it is. A moves list replaces all four moves, and an IVs line sets all six:
  stats it doesn't list are 31, as in Showdown. EVs, Tera Type and the like
  are ignored. Nicknames, gender, and Showdown's form names (`Linoone-Galar`
  for the sheet's `Linoone-G`) are understood.
- **Trainer Battles**: the slide-out list has one dropdown per split, e.g.
  "Route 104 Aqua Grunt Split". Each lists that split's trainers in game order,
  ending with the level-cap boss. You can also type in the filter box. Pick
  any trainer to see their team: each Pokemon's level, held item, ability,
  nature and moves. Fights with several trainers get a switcher: the rival's
  starter variants and tag-battle partners. Boss fights against two trainers
  with separate teams are split into a battle per trainer (Museum grunts #1
  and #2, Tate and Liza), so KOs are tracked against one team at a time. A
  split shows ✗ if any of its battles was lost, and ✓ once its boss battles
  are won.
  Drag Pokemon from your box (only this attempt's catches) into the six team
  slots. You can also click a box Pokemon to add or remove it. Drag between
  slots to swap, or back to the box to remove. Untick *Show Fainted Pokémon*
  to leave fainted Pokemon out of the box (remembered per browser). Mark each
  fight won or lost.
  A team stores **copies**: adding a Pokemon copies it as it is right then, so
  evolving or editing it in the Box later doesn't rewrite past fights (and
  editing a copy doesn't touch the box). Click a team member to see or edit
  that fight's copy. If any copy differs from the box, the fight shows *This
  fight used Pokémon that have since been changed*.
- **Battle Details & Notes** (the KO tracker): marking a battle Won or Lost
  opens it, and so do *Battle Details & Notes* and the notepad-and-pencil
  icon next to every battle you've recorded anything for. The enemy team
  sits above yours with a dot under each enemy and over each of your
  Pokemon. Drag from one of your dots to an enemy's for a KO by your Pokemon
  (green arrow), or from an enemy's dot to one of yours for a KO by the enemy
  (red arrow). Clicking one dot and then the other works too, and clicking an
  arrow removes it. Each Pokemon can only be knocked out once per fight, so
  a new arrow into it replaces the old one. A red arrow marks your Pokemon
  Fainted, both that fight's copy and the Pokemon in your box. Removing the
  arrow puts them back to OK (the box Pokemon stays Fainted while another
  fight still has a red arrow for it). For the rival, pick which starter
  variant you fought. Below the arrows is the battle's **Notes** box: what
  happened, what you wish had, what to try next time. It saves as you type.
  A battle with notes is kept even if you clear its team and result.
- **See Other Trainer's Solutions** (under *Fights* on Trainer Battles):
  swaps your team and box for the teams other attempts brought to the
  selected battle. That's your own earlier attempts and other trainers'
  (anonymous: just "Another trainer's attempt #N"). Wins come first, then
  unmarked fights, then losses. Pick one, or step through with ‹ ›, to see
  its team and KOs as a read-only KO board; hover a Pokemon for its set.
  Each attempt shows its own notes for the battle: another trainer's notes
  come with their team, never yours.
  Below, a bar chart shows how many of those teams brought each Pokemon.
  The button switches back to your team.
- **KO Analytics**: a bar chart of which Pokemon scored the most KOs this
  attempt, with the battles they scored them in.
- **Battles Brought**: a bar chart of how many battles each box Pokemon was
  on the team for this attempt, with how many were won, lost or not marked.
  Pokemon never brought are listed too, with 0.

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

Then open http://127.0.0.1:5000 and create an account. The database
(`instance/nuzlocke.db`) is created on first start, along with
`instance/secret_key`, which signs login cookies (keep it private; deleting it
logs everyone out). Set `NUZLOCKE_DB` to use a different database file; the
key is kept next to it.

## Accounts

Passwords are stored only as salted scrypt hashes (werkzeug's
`generate_password_hash`, scrypt N=2^15, r=8, p=1). Logins last 30 days in an
HttpOnly, SameSite=Lax cookie that is also Secure on the live site. Changing
your password or logging out everywhere ends all your other sessions. After 10
failed logins, an address has to wait 15 minutes, and it can create at most 5
accounts an hour. Every change to data must carry an `X-Requested-With`
header, which other sites can't make a browser send, so they can't make
changes on a visitor's behalf.

There's no email, so a forgotten password is reset from a console, which is
also how to change a role or set up an admin:

```powershell
.venv\Scripts\python.exe scripts\manage_account.py NAME                       # show the account
.venv\Scripts\python.exe scripts\manage_account.py NAME --password            # set its password (asked for, not echoed)
.venv\Scripts\python.exe scripts\manage_account.py NAME --role mod            # trainer, mod, content_creator or admin
.venv\Scripts\python.exe scripts\manage_account.py NAME --create --password --role admin
```

## Deploying (PythonAnywhere, free)

The live site runs on a free PythonAnywhere "Beginner" account. That plan
keeps the SQLite database on a persistent disk and serves HTTPS at
`<username>.pythonanywhere.com`.

First-time setup:

1. On the **Web** tab, *Add a new web app* → *Manual configuration* → *Python 3.11*.
2. Open a **Bash console** and run:

   ```bash
   git clone https://github.com/beninburley/nuzlocke_db.git ~/nuzlocke_db
   bash ~/nuzlocke_db/deploy/pythonanywhere_setup.sh
   ```

3. Back on the **Web** tab, set *Source code* to `/home/<username>/nuzlocke_db` and
   *Virtualenv* to `/home/<username>/.virtualenvs/nuzlocke`. Turn on **Force HTTPS**
   (login cookies are only sent over HTTPS). *Password protection* isn't needed:
   the site has its own accounts. Click **Reload**.
4. To bring your existing data along, upload your local `instance/nuzlocke.db` on
   the **Files** tab into `/home/<username>/nuzlocke_db/instance/`, replacing the
   file there. Then click **Reload**. From then on, the live site's database is the
   one to use.

To deploy an update after merging to `main`, re-run the setup script in a Bash
console. It pulls, installs dependencies and reloads the site.

Upgrading a database from before accounts (schema v3 or older) gives all its
attempts to the site owner's account (`SITE_OWNER` in `db.py`), created as an
admin with no password. Set one before logging in:

```bash
~/.virtualenvs/nuzlocke/bin/python ~/nuzlocke_db/scripts/manage_account.py bkewps --password
```

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

**The whole Pokédex** comes from PokeAPI too, so species, moves, abilities and
held items the spreadsheet never mentions can still be picked (e.g. when
correcting a trainer's team). The script adds every Pokémon and battle form to
`data/sprites.json`, named the sheet's way and without doubling forms the sheet
already has. It also writes every move, ability and held item's name to
`data/pokedex.json` for autocomplete. Gigantamax, Totem and costume forms are
left out. Re-run it when new Pokémon come out:

```powershell
.venv\Scripts\python.exe scriptsetch_pokedex.py
```

**Evolution lines** come from PokeAPI's evolution chains, cached in
`data/evolutions.json`. Regional forms keep their line (Growlithe-H ->
Arcanine-H). Re-run after re-extracting game data:

```powershell
.venv\Scripts\python.exe scripts\fetch_evolutions.py
```

**Past attempts** from the *Past Encounters* and *Past Boss Fights* tabs can be
imported (best effort) into an account, the site owner's unless `--user=NAME`
says otherwise. The account must exist (see *Accounts*):

```powershell
.venv\Scripts\python.exe scripts\import_history.py            # skips attempts already in the DB
.venv\Scripts\python.exe scripts\import_history.py --replace  # re-imports them
```

The import strips ability markers (`Lillipup-`), matches evolved or shorthand
names to catches through evolution families (`Grotle` -> the Turtwig starter,
`Zigzagoon` -> `Zigzagoon-G`), and fixes small typos. Battle copies get the
form the sheet lists for that fight, and each box Pokemon gets the latest form
it reached. A split boss fight (the Museum grunts, Tate & Liza) gets the
column's team and result on each of its battles. It puts "Killed:" rows and free-text notes into each attempt's
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
on startup. It first saves a copy next to it (e.g. `nuzlocke.backup-v3.db`).
Upgrading to v3 splits the Museum grunts and Tate & Liza into a battle per
trainer; fights already recorded there get the same team and result on both.
Upgrading to v4 adds accounts and gives every existing attempt to the site
owner. Upgrading to v5 gives each battle its own notes; the old per-attempt
notes stay in the database (`attempts.notes`) but are no longer shown.

## Rules enforced

Rules are checked in the API and again by SQLite triggers and constraints:

- every attempt belongs to one account, and each account changes only its own attempts (anyone
  else's show up as "not found"); attempt numbers are unique per account. The one thing shared
  is battle teams, KOs and battle notes in *See Other Trainer's Solutions*, without the account they came from
- usernames are 3-30 letters, digits, dots, dashes or underscores, unique ignoring case;
  passwords are 8-128 characters

- one catch per route per attempt, and what was caught must be in that route's encounter table
  (its current species can then evolve freely)
- level 1-100, IVs 0-31, status one of OK / Burn / Sleep / Fainted, nature one of the 25
- a team member must be a copy of a catch from the same attempt, with no duplicates and at most 6
- removing a route's catch keeps the battle copies made from it (they show as "no longer in box");
  changing the Pokemon caught on a route resets its current species
- a KO links one of the fight's team copies to a Pokemon of the enemy team fought; each Pokemon
  is knocked out at most once per fight, and removing a team member removes its KOs

## Layout

```
app.py                 Flask app: JSON API, pages, logins
accounts.py            Password hashing, username/password rules, rate limits, cookie key
box_script.py          Reading Showdown-style sets and matching them to box Pokemon
db.py                  SQLite connection, schema setup, migrations, game-data sync
schema.sql             Tables and integrity triggers
data/game_data.json    Extracted game data
data/sprites.json      Species -> PokeAPI sprite URL (the sheet's species plus the whole Pokédex)
data/pokedex.json      Every move, ability and held item name (PokeAPI)
data/evolutions.json   Species -> its evolutionary line (PokeAPI)
scripts/               Spreadsheet extraction, PokeAPI lookups, history import/backfill, accounts,
                       build_tokens.py (design-system/tokens.json -> static/tokens.css)
design-system/         nuzhub's design system: tokens, fonts, component specs (the source of truth for styling)
static/                Frontend (plain HTML/CSS/JS, no build step): landing.html, login.html,
                       account.html and site.js for accounts; index.html and app.js for the tracker;
                       admin.html and admin.js for admins (reusing app.js's rendering); tokens.css
                       (generated) and theme.js (light/dark toggle) on every page
```

### API

Every endpoint except the first five needs a login and works on the logged-in
account's data only. Changes (anything but GET) need an `X-Requested-With` header.

| Method | Path | Body |
|---|---|---|
| POST | `/api/signup` | `{username, password}`: creates a trainer account and logs in |
| POST | `/api/login` | `{username, password}` |
| POST | `/api/logout` | |
| GET | `/api/me` | the logged-in user `{username, role, created_at, attempts}`, or `null` |
| POST | `/api/me/password` | `{current_password, new_password}`; logs out the account's other sessions |
| POST | `/api/me/logout-everywhere` | ends every session of the account |
| GET | `/api/admin/users` | admins only: every account and its role, plus the roles |
| PATCH | `/api/admin/users/<id>` | admins only: `{role}` (not your own) |
| PUT | `/api/admin/trainer-team` | admins only: `{trainer: key, pokemon: [1-6 {species, level, item, ability, nature, moves}]}` corrects a trainer's team |
| POST | `/api/admin/trainer-team/revert` | admins only: `{trainer: key}` goes back to the spreadsheet's team |
| GET | `/api/game` | routes (with encounter options), battles, sprites, evolution lines, dupes-clause families, natures, statuses, suggestions |
| GET | `/api/battles/<id>` | a battle's trainers and their teams |
| GET | `/api/battles/<id>/solutions?exclude=<attempt id>` | every other attempt's team, KOs and notes for that battle, yours (`mine`) and other trainers' (anonymous; members by slot) |
| GET / POST | `/api/attempts` | `{number?}`; the list gives each attempt's `split` (null once every boss is beaten) and `split_lost` |
| GET / PATCH / DELETE | `/api/attempts/<id>` | `{number?, notes?}` |
| PUT | `/api/attempts/<id>/catches/<route_id>` | `{pokemon}` (null clears) |
| PATCH | `/api/catches/<id>` | any of `{species, level, ability, nature, item, moves: [4], ivs: {hp, atk, def, spa, spd, spe}, status}` |
| POST | `/api/attempts/<id>/box-script` | `{script, apply?}`: each set's box Pokemon and changes (or problem); with `apply: true`, saves them |
| PUT | `/api/attempts/<id>/fights/<battle_id>` | `{members: [slot] x6, result: "won" or "lost" or null}`; each slot is `null`, `{"id": copy}` (keep) or `{"catch_id": n}` (new copy) |
| PATCH | `/api/fight-members/<id>` | same fields as a catch; edits that battle's copy only |
| PATCH | `/api/fights/<id>` | `{notes}`: the battle's notes (at most 10,000 characters) |
| PUT | `/api/fights/<id>/kos` | `{trainer: key or null, kos: [{member: copy id, enemy: slot, by: "player" or "enemy"}]}` replaces the fight's KOs; returns the fight and any box Pokemon whose status changed (red arrows faint them) |

Fights (in `GET /api/attempts/<id>`) include `trainer` (the enemy team the KOs
were against, for battles with alternatives) and `kos`.

## Not in the MVP yet

- Trainer portraits (the sheet's *Sprites* tab embeds images rather than linking them)
- Tracking which trainers you've beaten or skipped (the *Trainers* tab's Status column)
- KOs for past attempts (the old sheet's "Killed:" rows are only in each attempt's notes)
- Failed or skipped encounters (a `-` in the old sheet)
- Email (password resets happen from a console), deleting an account
- Verification requests, and anything for the *mod* and *content creator* roles
- UI/UX polish
