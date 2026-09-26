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

-- Everything you can fight. Level-cap battles (the 23 boss fights) have a
-- level_cap and may involve several trainers: back-to-back or double battles,
-- a tag partner, or alternative teams (the rival's depends on your starter).
-- Every other trainer is a battle of its own, listed under (group_id) the
-- level-cap battle that follows it.
CREATE TABLE IF NOT EXISTS battles (
    id        INTEGER PRIMARY KEY,
    key       TEXT    NOT NULL UNIQUE,   -- stable identity when game data is re-synced
    name      TEXT    NOT NULL,
    location  TEXT,
    level_cap INTEGER,                   -- set only on level-cap battles
    group_id  INTEGER REFERENCES battles(id) ON DELETE SET NULL,  -- NULL on level-cap battles
    position  INTEGER NOT NULL
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

-- ---------------------------------------------------------------------------
-- User data.
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS attempts (
    id         INTEGER PRIMARY KEY,
    number     INTEGER NOT NULL UNIQUE,
    notes      TEXT    NOT NULL DEFAULT '',
    created_at TEXT    NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- What was caught on each route during an attempt (at most one per route).
CREATE TABLE IF NOT EXISTS catches (
    id         INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    route_id   INTEGER NOT NULL REFERENCES routes(id),
    pokemon    TEXT    NOT NULL,
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
    id         INTEGER PRIMARY KEY,
    attempt_id INTEGER NOT NULL REFERENCES attempts(id) ON DELETE CASCADE,
    battle_id  INTEGER NOT NULL REFERENCES battles(id),
    result     TEXT CHECK (result IN ('won', 'lost')),  -- NULL = not recorded
    UNIQUE (attempt_id, battle_id)
);

-- The team brought to a fight: up to six catches from the same attempt.
-- Clearing a route's catch removes it from any team it was on.
CREATE TABLE IF NOT EXISTS fight_members (
    fight_id INTEGER NOT NULL REFERENCES fights(id) ON DELETE CASCADE,
    slot     INTEGER NOT NULL CHECK (slot BETWEEN 1 AND 6),
    catch_id INTEGER NOT NULL REFERENCES catches(id) ON DELETE CASCADE,
    PRIMARY KEY (fight_id, slot),
    UNIQUE (fight_id, catch_id)
);

-- A team member must have been caught during the same attempt as the fight.
CREATE TRIGGER IF NOT EXISTS fight_members_same_attempt
BEFORE INSERT ON fight_members
WHEN (SELECT attempt_id FROM fights WHERE id = NEW.fight_id)
  IS NOT (SELECT attempt_id FROM catches WHERE id = NEW.catch_id)
BEGIN
    SELECT RAISE(ABORT, 'team member was not caught during this attempt');
END;
