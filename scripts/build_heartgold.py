"""Build HeartGold's game data (data/games/heartgold/) from the pret/pokeheartgold decompilation.

Everything comes from the game's own files except three hand-made tables below:
PROGRESSION (story order: which split each place belongs to, from Bulbapedia's walkthrough),
GIFTS (gift and static Pokémon that scripts give through variables) and OPTIONAL (trainers
you can walk past).

- Wild encounters: files/fielddata/encountdata/gs_enc_data.json (HeartGold's species where the
  versions differ), grouped by place (the map's section, e.g. Union Cave's three floors).
- Trainers: files/poketool/trainer/trainers.json (parties; moves the file leaves out are the
  Pokémon's last four level-up moves, from files/poketool/personal/wotbl.narc).
- Where trainers are: the map's NPCs (files/fielddata/eventdata/zone_event/, std_trainer) and
  scripted battles (files/fielddata/script/scr_seq/: TrainerBattle, MultiBattle).
- Names: the game's text (files/msgdata/msg/), matched to the site's spellings where they differ.

Usage:
    git clone --depth 1 --filter=blob:none --sparse https://github.com/pret/pokeheartgold.git <dir>
    (then sparse-checkout the folders above, include/constants/ and src/data/map_headers.h)
    python scripts/build_heartgold.py <dir>
"""
import json
import re
import struct
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "games" / "heartgold"

# Story order (Bulbapedia's HeartGold walkthrough): each split's boss and the places on the way
# to it. A place's wild encounters and trainers belong to its split.
PROGRESSION = [
    ("Leader Falkner", "TRAINER_LEADER_FALKNER_FALKNER",
     ["New Bark Town", "Route 29", "Cherrygrove City", "Route 30", "Route 31", "Violet City", "Sprout Tower"]),
    ("Leader Bugsy", "TRAINER_LEADER_BUGSY_BUGSY",
     ["Route 32", "Ruins of Alph", "Union Cave", "Route 33", "Azalea Town", "Slowpoke Well"]),
    ("Leader Whitney", "TRAINER_LEADER_WHITNEY", ["Ilex Forest", "Route 34", "Goldenrod City"]),
    ("Leader Morty", "TRAINER_LEADER_MORTY_MORTY",
     ["Route 35", "National Park", "Route 36", "Route 37", "Ecruteak City", "Burned Tower"]),
    ("Leader Chuck", "TRAINER_LEADER_CHUCK_CHUCK",
     ["Route 38", "Route 39", "Olivine City", "Lighthouse", "Route 40", "Route 41", "Cianwood City"]),
    ("Leader Jasmine", "TRAINER_LEADER_JASMINE_JASMINE", []),
    ("Leader Pryce", "TRAINER_LEADER_PRYCE_PRYCE",
     ["Route 42", "Mt. Mortar", "Mahogany Town", "Route 43", "Lake of Rage", "Team Rocket HQ"]),
    ("Leader Clair", "TRAINER_LEADER_CLAIR_CLAIR",
     ["Radio Tower", "Goldenrod Tunnel", "Route 44", "Ice Path", "Blackthorn City"]),
    ("Elite Four Will", "TRAINER_ELITE_FOUR_WILL_WILL",
     ["Dragon's Den", "Route 45", "Dark Cave", "Route 46", "Bell Tower", "Whirl Islands", "Route 27",
      "Tohjo Falls", "Route 26", "Victory Road", "Pokémon League"]),
    ("Elite Four Koga", "TRAINER_ELITE_FOUR_KOGA_KOGA", []),
    ("Elite Four Bruno", "TRAINER_ELITE_FOUR_BRUNO_BRUNO", []),
    ("Elite Four Karen", "TRAINER_ELITE_FOUR_KAREN_KAREN", []),
    ("Champion Lance", "TRAINER_CHAMPION_LANCE", []),
    ("Leader Lt. Surge", "TRAINER_LEADER_LT_SURGE_LT__SURGE", ["S.S. Aqua", "Vermilion City"]),
    ("Leader Sabrina", "TRAINER_LEADER_SABRINA_SABRINA", ["Route 6", "Saffron City"]),
    ("Leader Misty", "TRAINER_LEADER_MISTY_MISTY",
     ["Route 8", "Lavender Town", "Route 10", "Rock Tunnel", "Route 9", "Cerulean City", "Route 24", "Route 25",
      "Route 5"]),
    ("Leader Erika", "TRAINER_LEADER_ERIKA_ERIKA", ["Route 7", "Celadon City"]),
    ("Leader Janine", "TRAINER_LEADER_JANINE_JANINE", ["Route 16", "Route 17", "Route 18", "Fuchsia City"]),
    ("Leader Brock", "TRAINER_LEADER_BROCK_BROCK",
     ["Route 15", "Route 14", "Route 13", "Route 12", "Route 11", "Diglett's Cave", "Route 2", "Viridian Forest",
      "Pewter City"]),
    ("Leader Blaine", "TRAINER_LEADER_BLAINE_BLAINE",
     ["Route 3", "Mt. Moon", "Route 4", "Viridian City", "Route 1", "Pallet Town", "Route 21", "Cinnabar Island",
      "Route 20", "Seafoam Islands"]),
    ("Leader Blue", "TRAINER_LEADER_BLUE_BLUE", ["Route 19", "Route 22", "Route 28"]),
    ("Pkmn Trainer Red", "TRAINER_PKMN_TRAINER_RED_RED",
     ["Mt. Silver", "Mt. Silver Cave", "Cerulean Cave", "Cliff Edge Gate", "Route 47", "Cliff Cave", "Route 48"]),
]
# Maps whose battles come at another point in the story than the rest of their place.
MAP_SPLIT = {
    "T26GYM0101": "Leader Jasmine",      # Olivine Gym: after Cianwood
    "T02GYM0101": "Leader Blue",         # Viridian Gym: last in Kanto
    "T27R0501": "Elite Four Will",       # Ecruteak Dance Theater: the Kimono Girls, before Bell Tower
    "D37R0104": "Leader Clair",          # Goldenrod Underground: during the Radio Tower takeover
    "D37R0105": "Leader Clair",
}
# Place names as the site writes them (the game's text has some in capitals).
PLACE_NAMES = {"DIGLETT’s Cave": "Diglett's Cave", "SLOWPOKE Well": "Slowpoke Well", "Dragon’s Den": "Dragon's Den"}
# Maps left out: event-only places and battles (Celebi's Giovanni, the Sinjoh Ruins...).
SKIP_MAPS = {"D45R0102"}
# Battles left out: the Pokémon League lobby fights with the rival are post-game rematches (Lv 60).
SKIP_BATTLES = {"TRAINER_RIVAL_SILVER_19", "TRAINER_RIVAL_SILVER_20", "TRAINER_RIVAL_SILVER_21"}
# Moves Generation V renamed: the site uses today's names.
MOVE_RENAMES = {"Faint Attack": "Feint Attack", "Hi Jump Kick": "High Jump Kick", "ViceGrip": "Vise Grip"}
SKIP_MAP_WORDS = ("EVENT",)  # encounter tables of event-only map variants
# Gift and static Pokémon. Scripts give most through variables, so they're listed here:
# (place, method, species, level, note).
GIFTS = [
    ("Starter", "Gift", "Chikorita", 5, None), ("Starter", "Gift", "Cyndaquil", 5, None),
    ("Starter", "Gift", "Totodile", 5, None),
    ("Violet City", "Gift", "Togepi", 1, "Egg from Mr. Pokémon"),
    ("Violet City", "Gift", "Mareep", 1, "Egg from Primo"), ("Violet City", "Gift", "Wooper", 1, "Egg from Primo"),
    ("Violet City", "Gift", "Slugma", 1, "Egg from Primo"),
    ("Goldenrod City", "Gift", "Eevee", 5, "From Bill"),
    ("Route 36", "Static", "Sudowoodo", 20, None),
    ("Cianwood City", "Gift", "Shuckle", 15, "From Kirk"),
    ("Cianwood City", "Gift", "Tentacool", 15, None),
    ("Mt. Mortar", "Gift", "Tyrogue", 10, "From Kiyo"),
    ("Lake of Rage", "Static", "Gyarados", 30, "Red Gyarados"),
    ("Team Rocket HQ", "Static", "Electrode", 23, None),
    ("Union Cave", "Static", "Lapras", 20, "Fridays"),
    ("Dragon's Den", "Gift", "Dratini", 15, None),
    ("Bell Tower", "Static", "Ho-Oh", 45, None),
    ("Burned Tower", "Static", "Suicune", 40, None),
    ("Whirl Islands", "Static", "Lugia", 70, None),
    ("Route 10", "Static", "Zapdos", 50, None),
    ("Route 11", "Static", "Snorlax", 50, None),
    ("Seafoam Islands", "Static", "Articuno", 50, None),
    ("Mt. Silver Cave", "Static", "Moltres", 50, None),
    ("Pallet Town", "Gift", "Bulbasaur", 5, "From Professor Oak"),
    ("Pallet Town", "Gift", "Charmander", 5, "From Professor Oak"),
    ("Pallet Town", "Gift", "Squirtle", 5, "From Professor Oak"),
    ("Cerulean Cave", "Static", "Mewtwo", 70, None),
]
# Trainers you can walk past without being seen. Filled in from the maps; anything not
# listed is a trainer the route makes you fight.
OPTIONAL = set()

# Encounter slot chances (percent), Generation IV.
LAND_RATES = [20, 20, 10, 10, 10, 10, 5, 5, 4, 4, 1, 1]
SURF_RATES = [60, 30, 5, 4, 1]
ROD_RATES = {"old_rod": [60, 30, 5, 4, 1], "good_rod": [40, 40, 15, 4, 1], "super_rod": [40, 40, 15, 4, 1]}
ROCK_SMASH_RATES = [90, 10]
STARTERS = {"Chikorita": "Chikorita", "Bayleef": "Chikorita", "Meganium": "Chikorita",
            "Cyndaquil": "Cyndaquil", "Quilava": "Cyndaquil", "Typhlosion": "Cyndaquil",
            "Totodile": "Totodile", "Croconaw": "Totodile", "Feraligatr": "Totodile"}


def key(name):
    """Spelling-blind key: "Thunder Punch", "ThunderPunch" and "THUNDERPUNCH" match."""
    name = name.replace("♀", "f").replace("♂", "m")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", name.lower())


class Repo:
    def __init__(self, path):
        self.path = Path(path)

    def text(self, rel):
        return (self.path / rel).read_text(encoding="utf-8")

    def json(self, rel):
        return json.loads(self.text(rel))

    def msg(self, number):
        return [m.get("en_US", "") for m in self.json(f"files/msgdata/msg/msg_{number:04d}.json")["messages"]]

    def defines(self, rel, prefix):
        return {m.group(1): int(m.group(2))
                for m in re.finditer(rf"#define ({prefix}\w+)\s+(\d+)\b", self.text(rel))}


def narc_files(data):
    """The files inside a NARC archive."""
    assert data[:4] == b"NARC"
    pos = struct.unpack_from("<H", data, 12)[0]
    assert data[pos:pos + 4] == b"BTAF"
    size, count = struct.unpack_from("<IH", data, pos + 4)
    entries = [struct.unpack_from("<II", data, pos + 12 + 8 * i) for i in range(count)]
    pos += size
    assert data[pos:pos + 4] == b"BTNF"
    pos += struct.unpack_from("<I", data, pos + 4)[0]
    assert data[pos:pos + 4] == b"GMIF"
    base = pos + 8
    return [data[base + start:base + end] for start, end in entries]


class Names:
    """Game constants -> names: the site's spelling (PokeAPI's) where one matches, else the game's."""

    def __init__(self, repo):
        sprites = json.loads((ROOT / "data" / "sprites.json").read_text(encoding="utf-8"))
        dex = json.loads((ROOT / "data" / "pokedex.json").read_text(encoding="utf-8"))
        self.site = {kind: {key(n): n for n in names} for kind, names in
                     (("species", sorted(sprites, key=lambda n: ("'" in n or "’" in n, n))),
                      ("moves", dex["moves"]), ("items", dex["items"]), ("abilities", dex["abilities"]))}
        consts = lambda rel, prefix: {v: k for k, v in repo.defines(rel, prefix).items()}
        self.species_ids = repo.defines("include/constants/species.h", "SPECIES_")
        self.game = {
            "moves": (repo.defines("include/constants/moves.h", "MOVE_"), repo.msg(750)),
            "items": (repo.defines("include/constants/items.h", "ITEM_"), repo.msg(222)),
            "classes": (repo.defines("include/constants/trainer_class.h", "TRAINERCLASS_"), repo.msg(730)),
        }
        self.move_names = {i: n for n, i in self.game["moves"][0].items()}

    def species(self, const):
        word = const[len("SPECIES_"):]
        return self.site["species"].get(key(word.replace("_", ""))) or word.replace("_", " ").title()

    def _named(self, kind, site_kind, const):
        ids, texts = self.game[kind]
        text = texts[ids[const]] if const in ids and ids[const] < len(texts) else const.split("_", 1)[1].title()
        return self.site.get(site_kind, {}).get(key(text), text) if site_kind else text

    def move(self, const):
        name = self._named("moves", "moves", const)
        return MOVE_RENAMES.get(name, name)

    def item(self, const):
        return None if const in (None, "ITEM_NONE") else self._named("items", "items", const)

    def trainer_class(self, const):
        return self._named("classes", None, const)


def learnsets(repo, names):
    """species constant -> [(level, move constant)] in learn order."""
    files = narc_files((repo.path / "files/poketool/personal/wotbl.narc").read_bytes())
    by_id = {i: c for c, i in names.species_ids.items()}
    out = {}
    for species_id, blob in enumerate(files):
        moves = []
        for (value,) in struct.iter_unpack("<H", blob[: len(blob) // 2 * 2]):
            if value == 0xFFFF:
                break
            moves.append((value >> 9, names.move_names.get(value & 0x1FF)))
        if species_id in by_id:
            out[by_id[species_id]] = moves
    return out


def default_moves(learnset, level):
    """A wild or trainer Pokémon's moves without a moveset: the last four it learned by `level`."""
    known = []
    for learned_at, move in learnset:
        if learned_at > level:
            break
        if move and move not in known:
            known.append(move)
            known = known[-4:]
    return known


def version(value):
    """HeartGold's half of a value the versions differ in."""
    if isinstance(value, dict) and "HEARTGOLD" in value:
        return value["HEARTGOLD"]
    return value


def build(repo_path):
    repo = Repo(repo_path)
    names = Names(repo)
    moves_by_species = learnsets(repo, names)

    # Maps: code (R30) -> place name, from the map headers.
    mapsec_ids = repo.defines("include/constants/map_sections.h", "MAPSEC_")
    mapsec_text = repo.msg(279)
    place_of, enc_maps = {}, defaultdict(list)  # code -> place; place -> [(map const, encounter bank)]
    for m in re.finditer(r"\[(MAP_\w+)\] = \{(.*?)\n\s*\},", repo.text("src/data/map_headers.h"), re.S):
        get = lambda field: (re.search(rf"\.{field} = (\w+)", m.group(2)) or [None, None])[1]
        code = re.sub(r"^NARC_zone_event_\d+_(\w+)_bin$", lambda c: c.group(1), get("eventsBank") or "")
        place = mapsec_text[mapsec_ids[get("mapsec")]] if get("mapsec") in mapsec_ids else get("mapsec")
        place = PLACE_NAMES.get(place, place)
        place_of[code] = place
        bank = get("wildEncounterBank")
        if bank and bank != "ENCDATA_NA" and not any(w in m.group(1) for w in SKIP_MAP_WORDS):
            enc_maps[place].append((m.group(1), bank))

    split_of_place = {place: split for split, _, places in PROGRESSION for place in places}
    split_order = [split for split, _, _ in PROGRESSION]
    place_order = [place for _, _, places in PROGRESSION for place in places]

    # --- wild encounters ------------------------------------------------------------------
    # A map's encounter bank ENCDATA_R30 is the table whose "map" is R30.
    tables = {t["map"]: t for t in repo.json("files/fielddata/encountdata/gs_enc_data.json")["encounters"]}

    def table_for(bank):
        return tables.get(bank[len("ENCDATA_"):])

    routes = {}
    for place in place_order:
        slots = defaultdict(lambda: defaultdict(float))  # method -> species -> chance (summed over maps)
        levels = defaultdict(lambda: defaultdict(set))
        maps_with = defaultdict(int)  # method -> how many of the place's maps have it

        def add(method, species_const, rate, level):
            species_const = version(species_const)
            if not species_const or species_const == "SPECIES_NONE":
                return
            name = names.species(species_const)
            slots[method][name] += rate or 0
            if level is not None:
                levels[method][name].add(level)

        for map_const, bank in enc_maps.get(place, []):
            table = table_for(bank)
            if table is None:
                continue
            contest = "BUG_CATCHING" in map_const
            if table["land"]["rate"]:
                for time, label in (("morn", "morning"), ("day", "day"), ("nite", "night")):
                    method = "Bug Contest" if contest else f"Land ({label})"
                    maps_with[method] += 1
                    for mon, rate in zip(table["land"]["mons"], LAND_RATES):
                        level = version(mon["level"])
                        add(method, mon["species"][time] if isinstance(mon["species"], dict) and time in mon["species"]
                            else mon["species"], rate, level)
                    if contest:
                        break
            for field, method, rates in (("surf", "Surf", SURF_RATES), ("rock_smash", "Rock Smash", ROCK_SMASH_RATES)):
                if table[field]["rate"]:
                    maps_with[method] += 1
                    for mon, rate in zip(table[field]["mons"], rates):
                        lv = mon["level"]
                        add(method, mon["species"], rate, (version(lv["min"]), version(lv["max"])) if isinstance(lv, dict) else version(lv))
            for rod, rates in ROD_RATES.items():
                part = table["fishing"][rod]
                if part["rate"]:
                    method = rod.replace("_", " ").title()
                    maps_with[method] += 1
                    for mon, rate in zip(part["mons"], rates):
                        lv = mon["level"]
                        add(method, mon["species"], rate, (version(lv["min"]), version(lv["max"])) if isinstance(lv, dict) else version(lv))
            # Conditional slots: swarms (Professor Oak's news), the radio's Hoenn and Sinnoh Sounds.
            for field, method in (("landSwarm", "Swarm"), ("surfSwarm", "Swarm"), ("fishSwarm", "Swarm"),
                                  ("nightFish", "Fishing at night")):
                if table.get(field):
                    add(method, table[field], None, None)
            if table["land"]["rate"]:
                for field, method in (("hoenn", "Hoenn Sound"), ("sinnoh", "Sinnoh Sound")):
                    for species in table.get(field) or []:
                        add(method, species, None, None)

        encounters = []
        for method, species in slots.items():
            n = maps_with.get(method) or 1
            for name, total in species.items():
                lv = levels[method][name]
                flat = sorted({x for v in lv for x in (v if isinstance(v, tuple) else (v,))})
                encounters.append({"method": method, "pokemon": name,
                                   "rate": round(total / n, 2) if method in maps_with else None,
                                   "level": (f"{flat[0]}-{flat[-1]}" if len(flat) > 1 else str(flat[0])) if flat else None})
        if encounters:
            routes[place] = encounters
    gifts = defaultdict(list)
    for place, method, species, level, note in GIFTS:
        gifts[place].append({"method": method, "pokemon": species, "rate": None,
                             "level": f"{level}" + (f" ({note})" if note else "")})
    route_list = [{"name": "Starter", "encounters": gifts.pop("Starter")}]
    for place in place_order:
        if place in routes or place in gifts:
            route_list.append({"name": place, "encounters": routes.get(place, []) + gifts.pop(place, [])})
    assert not gifts, f"gifts for places not in PROGRESSION: {list(gifts)}"

    # --- trainers ----------------------------------------------------------------------
    trainer_ids = repo.defines("include/constants/trainers.h", "TRAINER_")
    trainer_data = repo.json("files/poketool/trainer/trainers.json")["trainers"]

    def party(const):
        t = trainer_data[trainer_ids[const]]
        team = []
        for mon in t["party"]:
            species = mon["species"]
            moves = [names.move(m) for m in mon.get("moves", []) if m and m != "MOVE_NONE"]
            if "moves" not in mon:
                moves = [names.move(m) for m in default_moves(moves_by_species.get(species, []), mon["level"])]
            team.append({"species": names.species(species), "level": mon["level"], "item": names.item(mon.get("item")),
                         "ability": None, "nature": None, "moves": moves})
        return t, team

    def trainer_name(const):
        t = trainer_data[trainer_ids[const]]
        return f"{names.trainer_class(t['class'])} {t['name'].replace('{TRNAME}', '').strip()}".strip()

    placed = []  # (code, [enemy consts], partner const or None), in map and script order
    seen = set()
    for f in sorted((repo.path / "files/fielddata/eventdata/zone_event").glob("*.json"), key=lambda p: p.name):
        code = f.stem.split("_", 1)[1]
        for obj in json.loads(f.read_text(encoding="utf-8")).get("objects", []):
            for const in re.findall(r"std_trainer\w*\((TRAINER_\w+)", str(obj.get("scriptId"))):
                if const not in seen:
                    seen.add(const)
                    placed.append((code, [const], None))
    story = re.compile(r"_\d+$")  # a numbered leader, Elite Four or Champion fight is a rematch
    for f in sorted((repo.path / "files/fielddata/script/scr_seq").glob("scr_seq_*_*.s")):
        code = f.stem.split("_", 3)[3]
        for line in f.read_text(encoding="utf-8").splitlines():
            single = re.match(r"\s*TrainerBattle (TRAINER_\w+)", line)
            multi = re.match(r"\s*MultiBattle (TRAINER_\w+), (TRAINER_\w+), (TRAINER_\w+)", line)
            if single:
                consts, partner = [single.group(1)], None
            elif multi:
                partner, consts = multi.group(1), [multi.group(2), multi.group(3)]
            else:
                continue
            first = consts[0]
            if first in seen or (story.search(first) and re.search(r"LEADER|ELITE_FOUR|CHAMPION|PKMN_TRAINER_RED", first)):
                continue
            if partner and "PARTNER" in partner:
                continue  # post-game tag battles alongside the rival
            seen.update(consts)
            placed.append((code, consts, partner))

    # Rival fights: the three starter variants of one fight are on one map.
    rival = re.compile(r"TRAINER_(RIVAL_SILVER|PASSERBY_BOY)")
    battles_by_split = defaultdict(list)
    boss_consts = {const: split for split, const, _ in PROGRESSION}
    rivals_done = set()
    unplaced = []
    for code, consts, partner in placed:
        if code in SKIP_MAPS or consts[0] in SKIP_BATTLES:
            continue
        place = place_of.get(code)
        split = MAP_SPLIT.get(code) or split_of_place.get(place)
        if consts[0] in boss_consts:
            split = boss_consts[consts[0]]
        if split is None:
            unplaced.append((code, place, consts[0]))
            continue
        if rival.match(consts[0]):
            if code in rivals_done:
                continue
            rivals_done.add(code)
            variants = [c for c2, cs, _ in placed if c2 == code for c in cs if rival.match(c)]
            trainers = []
            for const in variants:
                t, team = party(const)
                starter = next((STARTERS[p["species"]] for p in team if p["species"] in STARTERS), None)
                trainers.append({"key": const, "name": f"Rival Silver {starter} team" if starter else trainer_name(const),
                                 "location": place, "tags": [], "pokemon": team})
            battles_by_split[split].append({"key": f"trainer:rival@{code}", "name": "Rival Silver", "location": place,
                                            "trainers": trainers, "order": place_order.index(place) if place in place_order else 999})
            continue
        trainers = []
        for const in consts:
            t, team = party(const)
            tags = (["Double"] if t["double"] else []) + (["Optional"] if const in OPTIONAL else [])
            trainers.append({"key": const, "name": trainer_name(const), "location": place, "tags": tags, "pokemon": team})
        if partner:
            t, team = party(partner)
            trainers.append({"key": partner, "name": trainer_name(partner), "location": place, "tags": ["Tag Partner"],
                             "pokemon": team})
        name = " & ".join(t["name"] for t in trainers if "Tag Partner" not in t["tags"])
        battles_by_split[split].append({"key": f"trainer:{consts[0]}", "name": name, "location": place,
                                        "trainers": trainers, "order": place_order.index(place) if place in place_order else 999})

    battles = []
    for split, boss_const, _ in PROGRESSION:
        boss = next(b for b in battles_by_split[split] if b["trainers"][0]["key"] == boss_const)
        rest = sorted((b for b in battles_by_split[split] if b is not boss), key=lambda b: b["order"])
        for b in rest:
            b.pop("order")
            battles.append({**b, "level_cap": None, "split": None, "group": split})
        boss.pop("order")
        boss["trainers"][0]["tags"] = ["Boss"] + [t for t in boss["trainers"][0]["tags"] if t != "Optional"]
        cap = max(p["level"] for p in boss["trainers"][0]["pokemon"])
        battles.append({**boss, "key": f"boss:{split}", "name": split, "level_cap": cap, "split": split, "group": None})
    for b in battles:
        b["key"] = b["key"]
        b.setdefault("location", None)

    # Dupes-clause families: each evolutionary line (PokeAPI's, as the site uses), for every
    # species the game has.
    lines = json.loads((ROOT / "data" / "evolutions.json").read_text(encoding="utf-8"))
    species = {e["pokemon"] for r in route_list for e in r["encounters"]}
    species |= {p["species"] for b in battles for t in b["trainers"] for p in t["pokemon"]}
    families, done = [], set()
    for name in sorted(species):
        if name in done:
            continue
        family = sorted(set(lines.get(name, [name])) | {name})
        done.update(family)
        families.append(family)

    # Logic routing: a split's places open once the boss before it is beaten (the first split's from the start).
    route_names = {r["name"] for r in route_list}
    unlocks, previous = [{"after": None, "routes": ["Starter"]}], None
    for split, _, places in PROGRESSION:
        opened = [p for p in places if p in route_names]
        if opened:
            if previous is None:
                unlocks[0]["routes"] += opened
            else:
                unlocks.append({"after": previous, "routes": opened})
        previous = split
    routing = {"unlocks": unlocks, "areas": {}}

    data = {"source": "pret/pokeheartgold decompilation (HeartGold), via scripts/build_heartgold.py",
            "routes": route_list,
            "battles": [{k: b[k] for k in ("key", "name", "location", "level_cap", "group", "split", "trainers")}
                        for b in battles],
            "families": families}
    return data, routing, unplaced


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    sys.path.insert(0, str(ROOT))
    import db  # noqa: E402

    data, routing, unplaced = build(sys.argv[1])
    problems = db.validate_game_data(data)
    for p in problems:
        print("problem:", p)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "game.json").write_text(json.dumps({"name": "HeartGold"}, indent=2) + "\n", encoding="utf-8")
    (OUT / "game_data.json").write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    (OUT / "routing.json").write_text(json.dumps(routing, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    trainers = sum(len(b["trainers"]) for b in data["battles"])
    print(f"{len(data['routes'])} places, {len(data['battles'])} battles ({trainers} trainers), "
          f"{sum(1 for b in data['battles'] if b['split'])} splits, {len(data['families'])} families -> {OUT}")
    if unplaced:
        print(f"{len(unplaced)} battles on maps outside PROGRESSION (left out):",
              sorted({f'{place} ({code})' for code, place, _ in unplaced}))
    sys.exit(1 if problems else 0)


if __name__ == "__main__":
    main()
