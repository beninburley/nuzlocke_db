-- ---------------------------------------------------------------------------
-- Game data: loaded from data/game_data.json, identical for every attempt.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS routes (
    id       INTEGER PRIMARY KEY,
    name     TEXT    NOT NULL UNIQUE,
    position INTEGER NOT NULL
);

-- One row per encounter slot on the Encounters tab. The Pokemon that may be
-- recorded as caught on a route are the DISTINCT pokemon for that route.
CREATE TABLE IF NOT EXISTS route_encounters (
    id       INTEGER PRIMARY KEY,
    route_id INTEGER NOT NULL REFERENCES routes(id) ON DELETE CASCADE,
    method   TEXT    NOT NULL,   -- Land, Fishing, Surf, Rocks, Other
    pokemon  TEXT    NOT NULL,
    rate     REAL,               -- percent, e.g. 20.0
    level    TEXT,               -- '2-3', '5', 'Fossil', 'Badge 2', ...
    position INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_route_encounters_route ON route_encounters(route_id);

-- Everything you can fight, grouped into splits. Each split ends with a
-- level-cap battle (one of the 23 boss fights; `split` names the split).
-- Every other battle is listed under (group_id) the level-cap battle that ends
-- its split. A battle may involve several trainers: a tag partner, or
-- alternative teams (the rival's depends on your starter). A boss fight
-- against two trainers with separate teams (the Museum grunts, Tate & Liza)
-- is one battle per trainer: each has the level_cap, and all but the last
-- are listed under the last.
CREATE TABLE IF NOT EXISTS battles (
    id        INTEGER PRIMARY KEY,
    key       TEXT    NOT NULL UNIQUE,   -- stable identity when game data is re-synced
    name      TEXT    NOT NULL,
    location  TEXT,
    level_cap INTEGER,                   -- set only on level-cap battles
    group_id  INTEGER REFERENCES battles(id) ON DELETE SET NULL,  -- NULL on the battle ending a split
    position  INTEGER NOT NULL,
    split     TEXT                       -- name of the split this battle ends, else NULL
);

CREATE TABLE IF NOT EXISTS trainers (
    id        INTEGER PRIMARY KEY,
    battle_id INTEGER NOT NULL REFERENCES battles(id) ON DELETE CASCADE,
    key       TEXT    NOT NULL UNIQUE,   -- sheet name + location
    name      TEXT    NOT NULL,
    location  TEXT,
    tags      TEXT    NOT NULL DEFAULT '',  -- comma-separated: Optional, Double, Tag Partner, ...
    position  INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trainers_battle ON trainers(battle_id);

CREATE TABLE IF NOT EXISTS trainer_pokemon (
    trainer_id INTEGER NOT NULL REFERENCES trainers(id) ON DELETE CASCADE,
    slot       INTEGER NOT NULL,
    species    TEXT    NOT NULL,
    level      INTEGER,
    item       TEXT,
    ability    TEXT,
    nature     TEXT,
    move1      TEXT,
    move2      TEXT,
    move3      TEXT,
    move4      TEXT,
    PRIMARY KEY (trainer_id, slot)
);

-- Admins' corrections to a trainer's team. Game data is reloaded from
-- data/game_data.json on every start, which replaces trainer_pokemon; these
-- edits are applied again after each reload, so they last. Keyed by the
-- trainer's stable key; `pokemon` is a JSON list of {species, level, item,
-- ability, nature, moves}. Deleting the row reverts to the spreadsheet's team.
CREATE TABLE IF NOT EXISTS trainer_edits (
    trainer_key TEXT    PRIMARY KEY,
    pokemon     TEXT    NOT NULL,
    edited_by   INTEGER REFERENCES users(id) ON DELETE SET NULL,
    edited_at   TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Dupes-clause groups (evolution lines + regional forms).
CREATE TABLE IF NOT EXISTS species_families (
    species   TEXT    PRIMARY KEY,
    family_id INTEGER NOT NULL
);

-- Sprite image per species, from pokeapi.co (data/sprites.json).
CREATE TABLE IF NOT EXISTS species_sprites (
    species TEXT PRIMARY KEY,
    url     TEXT NOT NULL
);

-- Each species' evolutionary line, from pokeapi.co (data/evolutions.json):
-- a JSON list of the species it can evolve or devolve into, itself included.
CREATE TABLE IF NOT EXISTS evolution_lines (
    species TEXT PRIMARY KEY,
    members TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- User data.
-- ---------------------------------------------------------------------------

-- Accounts. Everyone who signs up is a 'trainer'; the other roles are only
-- labels for now. password_hash is a salted scrypt hash (see accounts.py);
-- NULL means the account can't log in until a password is set with
-- scripts/manage_account.py. session_epoch goes up when the password changes
-- or the user logs out everywhere, which ends every session made before.
CREATE TABLE IF NOT EXISTS users (
    id            INTEGER PRIMARY KEY,
    username      TEXT    NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT,
    role          TEXT    NOT NULL DEFAULT 'trainer'
                  CHECK (role IN ('trainer', 'mod', 'content_creator', 'admin')),
    session_epoch INTEGER NOT NULL DEFAULT 0,
    created_at    TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Each attempt belongs to one account; numbers are unique per account.
CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY,
    user_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    number     INTEGER NOT NULL,
    notes      TEXT    NOT NULL DEFAULT '',  -- general notes; no longer shown (notes are per battle now)
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (user_id, number)
);

-- The attempt's box: what was caught on each route (at most one per route).
-- `pokemon` is what was caught, checked against the route's encounter table;
-- `species` is what it is now, after evolving. The other columns are its
-- details, NULL until filled in.
CREATE TABLE IF NOT EXISTS catches (
    id         INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    route_id   INTEGER NOT NULL REFERENCES routes(id),
    pokemon    TEXT    NOT NULL,
    species    TEXT    NOT NULL,
    level      INTEGER CHECK (level BETWEEN 1 AND 100),
    ability    TEXT,
    nature     TEXT,
    item       TEXT,
    move1      TEXT,
    move2      TEXT,
    move3      TEXT,
    move4      TEXT,
    iv_hp      INTEGER CHECK (iv_hp  BETWEEN 0 AND 31),
    iv_atk     INTEGER CHECK (iv_atk BETWEEN 0 AND 31),
    iv_def     INTEGER CHECK (iv_def BETWEEN 0 AND 31),
    iv_spa     INTEGER CHECK (iv_spa BETWEEN 0 AND 31),
    iv_spd     INTEGER CHECK (iv_spd BETWEEN 0 AND 31),
    iv_spe     INTEGER CHECK (iv_spe BETWEEN 0 AND 31),
    status     TEXT    NOT NULL DEFAULT 'OK'
               CHECK (status IN ('OK', 'Burn', 'Sleep', 'Fainted')),
    UNIQUE (attempt_id, route_id)
);

-- A catch must be one of the Pokemon in that route's encounter table.
CREATE TRIGGER IF NOT EXISTS catches_valid_insert
BEFORE INSERT ON catches
WHEN NOT EXISTS (SELECT 1 FROM route_encounters
                 WHERE route_id = NEW.route_id AND pokemon = NEW.pokemon)
BEGIN
    SELECT RAISE(ABORT, 'pokemon is not in this route''s encounter table');
END;

CREATE TRIGGER IF NOT EXISTS catches_valid_update
BEFORE UPDATE OF pokemon, route_id ON catches
WHEN NOT EXISTS (SELECT 1 FROM route_encounters
                 WHERE route_id = NEW.route_id AND pokemon = NEW.pokemon)
BEGIN
    SELECT RAISE(ABORT, 'pokemon is not in this route''s encounter table');
END;

CREATE TABLE IF NOT EXISTS fights (
    id          INTEGER PRIMARY KEY,
    attempt_id  INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    battle_id   INTEGER NOT NULL REFERENCES battles(id),
    result      TEXT CHECK (result IN ('won', 'lost')),  -- NULL = not recorded
    -- The enemy team the KOs were against (a trainers.key), for battles with
    -- alternative teams. NULL = the battle's first enemy trainer.
    trainer_key TEXT,
    notes       TEXT NOT NULL DEFAULT '',  -- what happened in this battle, in the user's words
    UNIQUE (attempt_id, battle_id)
);

-- The team brought to a fight: up to six copies of box Pokemon, each taken
-- when it was added to the team. Evolving or editing the box Pokemon later
-- doesn't change the copy, and editing the copy doesn't change the box.
-- catch_id links a copy to its box Pokemon; it becomes NULL if that catch is
-- removed, and the copy stays as the record of what was used.
CREATE TABLE IF NOT EXISTS fight_members (
    -- AUTOINCREMENT: a copy's id is never reused after it's deleted, so a
    -- stale id can't end up pointing at a different copy.
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fight_id   INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    slot       INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 6),
    catch_id   INTEGER REFERENCES catches(id) ON DELETE SET NULL,
    species    TEXT    NOT NULL,
    level      INTEGER CHECK (level BETWEEN 1 AND 100),
    ability    TEXT,
    nature     TEXT,
    item       TEXT,
    move1      TEXT,
    move2      TEXT,
    move3      TEXT,
    move4      TEXT,
    iv_hp      INTEGER CHECK (iv_hp  BETWEEN 0 AND 31),
    iv_atk     INTEGER CHECK (iv_atk BETWEEN 0 AND 31),
    iv_def     INTEGER CHECK (iv_def BETWEEN 0 AND 31),
    iv_spa     INTEGER CHECK (iv_spa BETWEEN 0 AND 31),
    iv_spd     INTEGER CHECK (iv_spd BETWEEN 0 AND 31),
    iv_spe     INTEGER CHECK (iv_spe BETWEEN 0 AND 31),
    status     TEXT    NOT NULL DEFAULT 'OK'
               CHECK (status IN ('OK', 'Burn', 'Sleep', 'Fainted')),
    UNIQUE (fight_id, slot),
    UNIQUE (fight_id, catch_id)
);

-- A team member must have been caught during the same attempt as the fight.
CREATE TRIGGER IF NOT EXISTS fight_members_same_attempt
BEFORE INSERT ON fight_members
WHEN NEW.catch_id IS NOT NULL
 AND (SELECT attempt_id FROM fights WHERE id = NEW.fight_id)
     IS NOT (SELECT attempt_id FROM catches WHERE id = NEW.catch_id)
BEGIN
    SELECT RAISE(ABORT, 'team member was not caught during this attempt');
END;

-- Who knocked out whom in a fight: the KO tracker's arrows. ko_by 'player'
-- means the team member knocked out the enemy Pokemon in enemy_slot (a green
-- arrow); 'enemy' means that enemy Pokemon knocked out the team member (red).
-- Each Pokemon is knocked out at most once per fight.
CREATE TABLE IF NOT EXISTS fight_kos (
    id         INTEGER PRIMARY KEY,
    fight_id   INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    member_id  INTEGER NOT NULL REFERENCES fight_members(id) ON DELETE CASCADE,
    enemy_slot INTEGER NOT NULL CHECK (enemy_slot BETWEEN 1 AND 6),
    ko_by      TEXT    NOT NULL CHECK (ko_by IN ('player', 'enemy'))
);
CREATE INDEX IF NOT EXISTS idx_fight_kos_fight ON fight_kos(fight_id);
CREATE UNIQUE INDEX IF NOT EXISTS fight_kos_enemy_once ON fight_kos(fight_id, enemy_slot) WHERE ko_by = 'player';
CREATE UNIQUE INDEX IF NOT EXISTS fight_kos_member_once ON fight_kos(member_id) WHERE ko_by = 'enemy';

CREATE TRIGGER IF NOT EXISTS fight_kos_same_fight
BEFORE INSERT ON fight_kos
WHEN (SELECT fight_id FROM fight_members WHERE id = NEW.member_id) IS NOT NEW.fight_id
BEGIN
    SELECT RAISE(ABORT, 'KO team member is not in this fight');
END;
