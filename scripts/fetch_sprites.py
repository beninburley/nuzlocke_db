"""Map every species in data/game_data.json to its sprite on pokeapi.co.

Writes data/sprites.json ({species: sprite url or null}); the app loads it at
startup, so PokeAPI is only contacted when this script is (re)run.

Spreadsheet names are translated to PokeAPI names:
  "Zigzagoon-G" -> zigzagoon-galar, "Deerling-A" -> deerling-autumn,
  "Basculin-BS" -> basculin-blue-striped, "Farfetch'd-G" -> farfetchd-galar,
  "Lycanroc" -> lycanroc-midday (default form), "Cyndaquill" -> cyndaquil (typo)

Usage:
    python scripts/fetch_sprites.py
"""
import difflib
import json
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GAME_DATA = ROOT / "data" / "game_data.json"
OUT = ROOT / "data" / "sprites.json"
API = "https://pokeapi.co/api/v2"
SPRITE_BASE = "https://raw.githubusercontent.com/PokeAPI/sprites/master/sprites/pokemon"

# Spreadsheet form suffixes -> PokeAPI form suffixes, tried in order.
SUFFIXES = {
    "g": ["galar"],
    "a": ["alola", "autumn"],   # Alolan forms, but Deerling-A/Sawsbuck-A are Autumn
    "h": ["hisui"],
    "s": ["summer"],
    "w": ["winter"],
    "bs": ["blue-striped"],
}


def get_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "nuzlocke-db sprite fetcher"})
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def exists(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "nuzlocke-db sprite fetcher"})
    try:
        with urllib.request.urlopen(req, timeout=30):
            return True
    except urllib.error.HTTPError:
        return False


def slugify(name):
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    name = name.lower().replace("'", "").replace(".", "").replace(":", "")
    return "-".join(name.split())


def species_names():
    data = json.loads(GAME_DATA.read_text(encoding="utf-8"))
    names = {e["pokemon"] for r in data["routes"] for e in r["encounters"]}
    names |= {s for family in data["families"] for s in family}
    return sorted(names)


def resolve(name, pokemon_ids, forms, fixes):
    """Return the PokeAPI pokemon-form name for a spreadsheet species name."""
    slug = slugify(name)
    if slug in pokemon_ids or slug in forms:
        return slug
    base, _, suffix = slug.rpartition("-")
    for alt in SUFFIXES.get(suffix, []):
        if f"{base}-{alt}" in pokemon_ids or f"{base}-{alt}" in forms:
            return f"{base}-{alt}"
    # Species whose plain name isn't a PokeAPI pokemon (lycanroc -> lycanroc-midday):
    # use the default variety, i.e. the lowest id.
    variants = [p for p in pokemon_ids if p.startswith(slug + "-")]
    if variants:
        return min(variants, key=pokemon_ids.get)
    close = difflib.get_close_matches(slug, pokemon_ids, n=1, cutoff=0.85)
    if close:
        fixes[name] = close[0]
        return close[0]
    return None


def main():
    pokemon = get_json(f"{API}/pokemon?limit=100000")["results"]
    pokemon_ids = {p["name"]: int(p["url"].rstrip("/").split("/")[-1]) for p in pokemon}
    forms = {f["name"]: f["url"] for f in get_json(f"{API}/pokemon-form?limit=100000")["results"]}

    fixes, missing = {}, []
    resolved = {}
    for name in species_names():
        api_name = resolve(name, pokemon_ids, forms, fixes)
        if api_name is None:
            missing.append(name)
        resolved[name] = api_name

    def by_id(pokemon_id):
        # The URL PokeAPI's /pokemon endpoint reports as sprites.front_default.
        url = f"{SPRITE_BASE}/{pokemon_id}.png"
        return url if exists(url) else None

    def sprite(api_name):
        # Real varieties (zigzagoon-galar) have sprites on /pokemon; their
        # /pokemon-form entries often report none.
        if api_name in pokemon_ids and (url := by_id(pokemon_ids[api_name])):
            return api_name, url
        # Cosmetic forms (vivillon-archipelago, deerling-autumn) only exist as
        # forms; fall back to the parent pokemon if the form has no sprite.
        if api_name in forms:
            form = get_json(forms[api_name])
            if form["sprites"]["front_default"]:
                return api_name, form["sprites"]["front_default"]
            return api_name, by_id(form["pokemon"]["url"].rstrip("/").split("/")[-1])
        return api_name, None

    wanted = sorted({n for n in resolved.values() if n})
    with ThreadPoolExecutor(max_workers=6) as pool:
        sprites = dict(pool.map(sprite, wanted))

    result = {name: sprites.get(api_name) if api_name else None
              for name, api_name in resolved.items()}
    OUT.write_text(json.dumps(result, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    no_sprite = [n for n, url in result.items() if url is None and n not in missing]
    print(f"Wrote {OUT}: {sum(1 for u in result.values() if u)}/{len(result)} species have sprites")
    for name, api_name in sorted(fixes.items()):
        print(f"  corrected: {name} -> {api_name}")
    for name in missing:
        print(f"  not found on PokeAPI: {name}")
    for name in no_sprite:
        print(f"  no sprite on PokeAPI: {name} ({resolved[name]})")


if __name__ == "__main__":
    main()
