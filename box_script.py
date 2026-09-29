"""Update box Pokemon from a Showdown-style script (the "Update - Script" popup).

    Abomasnow @ Lum Berry
    Level: 43
    Hasty Nature
    Ability: Soundproof
    IVs: 4 SpA
    - Wood Hammer
    - Ice Beam
    - Ice Shard
    - Earthquake

Sets are separated by blank lines. Each set updates the box Pokemon of that
species or of its evolutionary line, evolving it if the script names a later
(or earlier) stage. It never creates a Pokemon. Anything a set leaves out stays
as it is; a moves list replaces all four moves, and an IVs line sets all six
IVs (stats it doesn't list are 31, as in Showdown). EVs, Tera Type and the
like aren't tracked, so they're ignored.
"""
import difflib
import re
import unicodedata
from dataclasses import dataclass, field

MAX_SCRIPT = 50_000  # characters
IV_NAMES = {"hp": "hp", "atk": "atk", "def": "def", "spa": "spa", "spd": "spd", "spe": "spe"}
# Showdown lines for things the tracker doesn't record.
IGNORED_KEYS = {"evs", "shiny", "happiness", "friendship", "tera type", "hidden power", "gigantamax",
                "dynamax level", "pokeball", "ball", "gender"}


@dataclass
class ScriptSet:
    line: int                                    # line number of the set's first line
    name: str                                    # the species as written
    details: dict = field(default_factory=dict)  # level, ability, nature, item, moves, ivs (as given)
    ignored: list = field(default_factory=list)  # lines or fields that were skipped
    problem: str | None = None


def parse(script):
    """Showdown-style text -> [ScriptSet]."""
    sets, current = [], None
    for number, raw in enumerate(script.splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("==="):  # a blank line (or a team header) ends a set
            current = None
            continue
        if current is None:
            current = start_set(number, line)
            sets.append(current)
        else:
            read_line(current, number, line)
    for s in sets:
        moves = s.details.get("moves")
        if moves is not None and len(moves) > 4 and not s.problem:
            s.problem = f"{s.name} has {len(moves)} moves; a Pokémon knows at most 4."
    return sets


def start_set(number, line):
    """First line: "Species", "Species @ Item", "Nickname (Species) (M) @ Item"."""
    head, at, item = line.partition("@")
    head = re.sub(r"\s*\((?:M|F)\)\s*$", "", head.strip())
    nicknamed = re.fullmatch(r"(.*?)\s*\(([^()]+)\)", head)
    name = (nicknamed.group(2) if nicknamed else head).strip()
    s = ScriptSet(line=number, name=name)
    if not name:
        s.problem = f"Line {number}: a set has to start with the Pokémon's species."
    if at:
        s.details["item"] = item.strip() or None
    return s


def read_line(s, number, line):
    if line.startswith("-"):
        s.details.setdefault("moves", []).append(line[1:].strip() or None)
        return
    nature = re.fullmatch(r"([A-Za-z]+)\s+Nature", line, re.IGNORECASE)
    if nature:
        s.details["nature"] = nature.group(1).capitalize()
        return
    key, colon, value = line.partition(":")
    key, value = key.strip().lower(), value.strip()
    if not colon:
        s.ignored.append(line)
    elif key == "ability":
        s.details["ability"] = value or None
    elif key == "level":
        if value.isdigit():
            s.details["level"] = int(value)
        else:
            s.problem = s.problem or f"Line {number}: the level should be a number, not {value!r}."
    elif key == "ivs":
        ivs = read_ivs(value)
        if ivs is None:
            s.problem = s.problem or f"Line {number}: IVs look like \"31 HP / 4 SpA\"."
        else:
            s.details["ivs"] = ivs
    elif key in IGNORED_KEYS:
        s.ignored.append(line.partition(":")[0].strip())
    else:
        s.ignored.append(line)


def read_ivs(value):
    """ "4 SpA / 0 Atk" -> all six IVs, the ones not listed being 31. None if unreadable."""
    ivs = dict.fromkeys(IV_NAMES.values(), 31)
    for part in value.split("/"):
        m = re.fullmatch(r"\s*(\d+)\s+([A-Za-z]+)\s*", part)
        if not m or m.group(2).lower() not in IV_NAMES:
            return None
        ivs[IV_NAMES[m.group(2).lower()]] = int(m.group(1))
    return ivs


# ---------------------------------------------------------------------------
# Species names: Showdown's (Zigzagoon-Galar, Farfetch’d) vs the sheet's
# (Zigzagoon-G, Farfetch'd)
# ---------------------------------------------------------------------------

def normalize(name):
    name = name.replace("♀", "-f").replace("♂", "-m")
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9-]", "", name.lower())


def resolve(name, names):
    """The species in `names` that `name` means, or None.

    Allows for spelling (Farfetch’d / Farfetch'd), Showdown's long form names
    (Arcanine-Hisui -> Arcanine-H), a name without its form when `names` has
    only one form of it (Zigzagoon -> Zigzagoon-G), and small typos.
    """
    by_key = {normalize(n): n for n in names}
    key = normalize(name)
    if key in by_key:
        return by_key[key]
    base, _, form = key.partition("-")
    same_base = [(k.partition("-")[2], n) for k, n in by_key.items() if k.partition("-")[0] == base]
    if form:
        hits = [n for f, n in same_base if f and (form.startswith(f) or f.startswith(form))]
    else:
        hits = [n for _, n in same_base]
    if len(hits) == 1:
        return hits[0]
    close = difflib.get_close_matches(key, list(by_key), n=1, cutoff=0.85)
    return by_key[close[0]] if close and not hits else None


def match(name, box, lines, families, taken=()):
    """Which box Pokemon a set for `name` updates, and the species it becomes.

    `box` is [{"id", "pokemon", "species", "route"}]; `lines` maps species to
    its evolutionary line and `families` maps species to its dupes-clause
    family (regional forms included). A Pokemon already of that species wins;
    otherwise one whose line (or family) includes it. Returns (mon, species,
    None) or (None, None, problem).
    """
    family_members = {}
    for species, family in families.items():
        family_members.setdefault(family, set()).add(species)
    exact, related = [], []
    for mon in box:
        if mon["id"] in taken:
            continue
        line = {mon["species"], mon["pokemon"], *lines.get(mon["species"], ()), *lines.get(mon["pokemon"], ())}
        target = resolve(name, line)
        if target is None:
            family = families.get(mon["species"], families.get(mon["pokemon"]))
            target = resolve(name, family_members.get(family, ())) if family is not None else None
        if target is not None:
            (exact if target == mon["species"] else related).append((mon, target))
    for tier in (exact, related):
        if len(tier) == 1:
            return tier[0][0], tier[0][1], None
        if len(tier) > 1:
            which = ", ".join(f"{mon['species']} ({mon['route']})" for mon, _ in tier)
            return None, None, (f"More than one Pokémon in your box could be this {name}: {which}. "
                                "Update it on the Box tab instead.")
    return None, None, (f"There's no {name} (or anything in its evolutionary line) in your box. "
                        "Add it on the Encounters tab first.")
