# MonSlot

One Pokémon in the team or box grid: sprite, nickname, level, where it was met, and its state chip.

- Slots sit on `surface` at `radius-md` with `shadow-1` and lift on hover. Selected (`is-selected`) adds an `emerald` 2px border on `emerald-soft`.
- Fainted (`is-fainted`) shows the sprite in grayscale at 55% opacity. The text stays full strength.
- Empty slots are dashed wells on `surface-sunken`.
- Sprites are `sprite-lg`. The preview uses initials where the sprite goes; real sprites come from the app's game data, with `image-rendering: pixelated`.
- The consumer provides the sprite URL, nickname, species, level, location, state and selected flag.
