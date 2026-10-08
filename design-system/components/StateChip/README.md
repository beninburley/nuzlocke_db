# StateChip

Shows a Pokémon's fate in the run: alive, fainted, boxed, caught, missed, gift or trade.

- Always use icon plus word. Colors come from `state-<name>` (background) and `state-<name>-ink` (text and icon). Icons are in `assets/StateIcons`.
- Fainted is the only dark chip, so it never depends on red vs green.
- In very tight table cells you can show the icon alone, but give it an `aria-label` and a tooltip with the word.
- The consumer provides the state, plus an optional count ("5 alive").
