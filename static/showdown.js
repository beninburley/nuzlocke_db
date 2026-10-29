"use strict";

// Showdown export: Pokémon as a Showdown paste, for the damage calculator. The reverse of
// "Update from script" (box_script.py), which reads these back. No DOM here, so
// scripts/check_showdown_export.py can run it under Node.

// The sheet's short form suffixes -> Showdown's ("Zigzagoon-G" -> "Zigzagoon-Galar"), as in
// scripts/fetch_sprites.py. "-F" (Indeedee-F, Nidoran-F) is already Showdown's spelling.
const SHOWDOWN_SUFFIXES = { G: "Galar", A: "Alola", H: "Hisui", S: "Summer", W: "Winter", BS: "Blue-Striped", T: "Therian" };
const AUTUMN_FORMS = new Set(["Deerling", "Sawsbuck"]);  // their "-A" is Autumn, not Alola
// Typos in the sheet. box_script.SHEET_TYPOS reads them back as the same Pokémon.
const SHOWDOWN_FIXES = { Cyndaquill: "Cyndaquil", "Hakomo-o": "Hakamo-o" };
const SHOWDOWN_IVS = [["hp", "HP"], ["atk", "Atk"], ["def", "Def"], ["spa", "SpA"], ["spd", "SpD"], ["spe", "Spe"]];

/** The species as Showdown names it. */
function showdownName(species) {
  if (SHOWDOWN_FIXES[species]) return SHOWDOWN_FIXES[species];
  const m = /^(.+)-([A-Z]{1,2})$/.exec(species);
  if (!m || !SHOWDOWN_SUFFIXES[m[2]]) return species;
  const form = m[2] === "A" && AUTUMN_FORMS.has(m[1]) ? "Autumn" : SHOWDOWN_SUFFIXES[m[2]];
  return `${m[1]}-${form}`;
}

/**
 * One Pokémon ({species, level, ability, nature, item, moves, ivs?}) as a Showdown set. Lines whose
 * value is missing are left out. IVs list only the known stats that aren't 31; none known, no line.
 */
function showdownSet(mon) {
  const ivs = SHOWDOWN_IVS.filter(([stat]) => mon.ivs?.[stat] != null && mon.ivs[stat] !== 31)
    .map(([stat, label]) => `${mon.ivs[stat]} ${label}`);
  return [
    showdownName(mon.species) + (mon.item ? ` @ ${mon.item}` : ""),
    mon.ability && `Ability: ${mon.ability}`,
    mon.level && `Level: ${mon.level}`,
    mon.nature && `${mon.nature} Nature`,
    ivs.length && `IVs: ${ivs.join(" / ")}`,
    ...(mon.moves ?? []).filter(Boolean).map((move) => `- ${move}`),
  ].filter(Boolean).join("\n");
}

/** Several Pokémon as one paste, a blank line between sets. */
function showdownText(mons) {
  return mons.map(showdownSet).join("\n\n") + "\n";
}

if (typeof module !== "undefined") module.exports = { showdownName, showdownSet, showdownText };
