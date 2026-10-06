"""Snapshot the whole Pokédex from PokeAPI, so any Pokémon, move, ability or
held item can be picked (not only the ones in the spreadsheet).

  * Every Pokémon and battle form PokeAPI has (bar Gigantamax, Totem, Pikachu's
    caps and costumes and the like) is added to data/sprites.json, which is
    the list of species the app knows. Names follow the sheet: the English
    name, plus the form ("Vileplume", "Meowth-Galar", "Charizard-Mega-X").
    Species the sheet already has, under its own names ("Zigzagoon-G"), are
    left as they are and not added twice.
  * Every move, ability and held item's English name goes to
    data/pokedex.json, for the autocomplete lists.

The app reads both files at startup, so PokeAPI is only contacted when this
script runs. Re-run it when new Pokémon come out.

Usage:
    python scripts/fetch_pokedex.py
"""
import json
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fetch_sprites import API, OUT as SPRITES, SPRITE_BASE, exists, get_json, resolve  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "pokedex.json"
GRAPHQL = "https://graphql.pokeapi.co/v1beta2"
ENGLISH = 9

# Forms that never come up in a Run & Bun battle.
SKIPPED_FORMS = ("-gmax", "-totem", "-eternamax", "-cap", "-starter", "-rock-star", "-belle", "-pop-star",
                 "-phd", "-libre", "-cosplay")
# Item categories a Pokémon can hold in battle (PokeAPI's "holdable" tag misses
# most of them: mega stones, berries, Eviolite...).
HELD_ITEM_CATEGORIES = [
    "effort-drop", "medicine", "other", "in-a-pinch", "picky-healing", "type-protection",  # berries
    "held-items", "choice", "bad-held-items", "training", "effort-training", "plates", "species-specific",
    "type-enhancement", "jewels", "mega-stones", "memories", "z-crystals", "evolution", "scarves",
]


def graphql(query):
    req = urllib.request.Request(GRAPHQL, data=json.dumps({"query": query}).encode(),
                                 headers={"Content-Type": "application/json", "User-Agent": "nuzlocke-db pokedex fetcher"})
    with urllib.request.urlopen(req, timeout=120) as res:
        out = json.load(res)
    if "errors" in out:
        raise SystemExit(f"PokeAPI GraphQL error: {out['errors']}")
    return out["data"]


def tidy(name):
    """PokeAPI writes "King’s Rock"; the sheet writes "King's Rock"."""
    return name.replace("’", "'")


def display_name(pokemon, species):
    """sheet-style name: "Vileplume" for a species' default form, else "Meowth-Galar"."""
    english, slug = species
    if pokemon["is_default"]:
        return english
    form = pokemon["name"][len(slug) + 1:] if pokemon["name"].startswith(slug + "-") else pokemon["name"]
    return f"{english}-{'-'.join(part.capitalize() for part in form.split('-'))}"


def main():
    data = graphql("""{
      pokemon(order_by: {id: asc}) { id name is_default pokemon_species_id }
      species: pokemonspecies { id name pokemonspeciesnames(where: {language_id: {_eq: %d}}) { name } }
      moves: movename(where: {language_id: {_eq: %d}}) { name }
      abilities: abilityname(where: {language_id: {_eq: %d}}) { name }
      items: itemname(where: {language_id: {_eq: %d}, item: {itemcategory: {name: {_in: %s}}}}) { name }
    }""" % (ENGLISH, ENGLISH, ENGLISH, ENGLISH, json.dumps(HELD_ITEM_CATEGORIES)))
    species = {s["id"]: (s["pokemonspeciesnames"][0]["name"], s["name"]) for s in data["species"]}

    # What the sheet's names already stand for, so nothing is added twice.
    sprites = json.loads(SPRITES.read_text(encoding="utf-8"))
    pokemon_ids = {p["name"]: p["id"] for p in data["pokemon"]}
    forms = {f["name"]: f["url"] for f in get_json(f"{API}/pokemon-form?limit=100000")["results"]}
    covered = {resolve(name, pokemon_ids, forms, {}) for name in sprites}
    known = {name.lower() for name in sprites}

    new = []
    for p in data["pokemon"]:
        if p["name"] in covered or any(skip in p["name"] for skip in SKIPPED_FORMS):
            continue
        name = display_name(p, species[p["pokemon_species_id"]])
        if name.lower() not in known:
            new.append((name, p["id"]))
            known.add(name.lower())

    def sprite(entry):
        name, pokemon_id = entry
        url = f"{SPRITE_BASE}/{pokemon_id}.png"
        return name, url if exists(url) else None

    with ThreadPoolExecutor(max_workers=8) as pool:
        added = dict(pool.map(sprite, new))
    sprites.update(added)
    SPRITES.write_text(json.dumps(sprites, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    dex = {
        "source": "pokeapi.co",
        "fetched": date.today().isoformat(),
        # Max and G-Max moves only exist when Dynamaxed, which Run & Bun doesn't have.
        "moves": sorted({tidy(m["name"]) for m in data["moves"] if not m["name"].startswith(("Max ", "G-Max "))}),
        "abilities": sorted({tidy(a["name"]) for a in data["abilities"]}),
        "items": sorted({tidy(i["name"]) for i in data["items"]}),
    }
    OUT.write_text(json.dumps(dex, indent=1, ensure_ascii=False), encoding="utf-8")

    no_sprite = sorted(name for name, url in added.items() if not url)
    print(f"Added {len(added)} Pokémon to {SPRITES.name} ({len(sprites)} in all); "
          f"{len(added) - len(no_sprite)} have sprites.")
    print(f"Wrote {OUT.name}: {len(dex['moves'])} moves, {len(dex['abilities'])} abilities, {len(dex['items'])} held items.")
    if no_sprite:
        print(f"No sprite on PokeAPI yet ({len(no_sprite)}): {', '.join(no_sprite)}")


if __name__ == "__main__":
    main()
