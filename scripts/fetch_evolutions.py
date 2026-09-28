"""Build data/evolutions.json: every box species' evolutionary line, from pokeapi.co.

A box Pokemon can be any species from the Encounters tab or the dupes-clause
families, in the spreadsheet's naming ("Zigzagoon-G", "Growlithe-H"). For each
one this lists the members of its PokeAPI evolution chain in that same naming,
in chain order, so the Box tab's Evolve popup can evolve or devolve to any of
them. The app loads the file at startup; PokeAPI is only contacted when this
script is (re)run.

Regional and cosmetic forms keep their line where the form exists:
  Zigzagoon-G -> [Zigzagoon-G, Linoone-G, Obstagoon]
  Growlithe-H -> [Growlithe-H, Arcanine-H]
  Deerling-A  -> [Deerling-A, Sawsbuck-A]
Base forms list every form of each member: Growlithe -> [Growlithe,
Growlithe-H, Arcanine, Arcanine-H]. A member missing from the encounter tables
and families (the sheet's Tyrogue family has no Hitmontop) uses the name the
trainer data gives it. Species not in the game data at all are left out.

Usage:
    python scripts/fetch_evolutions.py
"""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fetch_sprites import API, get_json, resolve

ROOT = Path(__file__).resolve().parent.parent
GAME_DATA = ROOT / "data" / "game_data.json"
OUT = ROOT / "data" / "evolutions.json"


def species_names_in_game_data():
    """(box names, trainer-only names): the sheet's encounter/family naming comes first."""
    data = json.loads(GAME_DATA.read_text(encoding="utf-8"))
    names = {e["pokemon"] for r in data["routes"] for e in r["encounters"]}
    names |= {s for family in data["families"] for s in family}
    trainer = {p["species"] for b in data["battles"] for t in b["trainers"] for p in t["pokemon"]}
    return sorted(names), sorted(trainer - names)


def chain_order(node, out):
    """Species names of an evolution chain, depth-first (base, then each branch)."""
    out.append(node["species"]["name"])
    for child in node["evolves_to"]:
        chain_order(child, out)
    return out


def main():
    pokemon = get_json(f"{API}/pokemon?limit=100000")["results"]
    pokemon_ids = {p["name"]: int(p["url"].rstrip("/").split("/")[-1]) for p in pokemon}
    forms = {f["name"]: f["url"] for f in get_json(f"{API}/pokemon-form?limit=100000")["results"]}
    species_names = {s["name"] for s in get_json(f"{API}/pokemon-species?limit=100000")["results"]}

    chain_urls = [c["url"] for c in get_json(f"{API}/evolution-chain?limit=100000")["results"]]
    with ThreadPoolExecutor(max_workers=6) as pool:
        chains = [chain_order(c["chain"], []) for c in pool.map(get_json, chain_urls)]
    chain_of = {species: chain for chain in chains for species in chain}

    def split(api_name):
        """'zigzagoon-galar' -> ('zigzagoon', 'galar'); 'mr-mime' -> ('mr-mime', '')."""
        parts = api_name.split("-")
        for i in range(len(parts), 0, -1):
            if "-".join(parts[:i]) in species_names:
                return "-".join(parts[:i]), "-".join(parts[i:])
        return api_name, ""

    box_names, trainer_names = species_names_in_game_data()
    fixes, unresolved = {}, []

    def forms_by_species(names, report):
        """species -> [(our name, form suffix)]"""
        out = {}
        for name in names:
            api_name = resolve(name, pokemon_ids, forms, fixes)
            if api_name is None:
                if report:
                    unresolved.append(name)
                continue
            species, suffix = split(api_name)
            out.setdefault(species, []).append((name, suffix))
        return out

    forms_of = forms_by_species(box_names, report=True)
    trainer_forms_of = forms_by_species(trainer_names, report=False)

    def variants_of(species):
        return forms_of.get(species) or trainer_forms_of.get(species)

    lines, missing = {}, set()
    todo = [(name, species, suffix) for species, variants in forms_of.items() for name, suffix in variants]
    done = set()
    while todo:
        name, species, suffix = todo.pop()
        if name in done:
            continue
        done.add(name)
        line = []
        for member in chain_of.get(species, [species]):
            variants = variants_of(member)
            if not variants:
                missing.add(member)
                continue
            if member not in forms_of:  # trainer-named fallback: give it a line too
                todo += [(n, member, s) for n, s in variants]
            same_form = [n for n, s in variants if s == suffix]
            line += same_form if suffix and same_form else [n for n, _ in variants]
        line = list(dict.fromkeys(line))  # de-duplicate, keep chain order
        if len(line) > 1:
            lines[name] = line

    OUT.write_text(json.dumps(lines, indent=1, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print(f"Wrote {OUT}: {len(lines)} species can evolve or devolve "
          f"({len(done) - len(lines)} have no other forms in their line)")
    if unresolved:
        print(f"  not found on PokeAPI: {unresolved}")
    print(f"  {len(missing)} chain members aren't in the game data and were left out: {sorted(missing)}")


if __name__ == "__main__":
    main()
