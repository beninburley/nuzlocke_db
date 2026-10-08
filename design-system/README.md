nuzhub is where Nuzlockers log their runs, read their stats, celebrate wins, and look up how other people handled the same fight. It should feel **modern, playful, calm**: a polished tool built for fun, not a business dashboard. One deep emerald, soft rounded cards that lift off the page, and a clear color plus icon for every Pokémon's fate.

## Principles

1. **Calm by default, playful in the moments.** Neutral surfaces and one emerald do the everyday work. Playfulness comes from rounded shapes, friendly words and the `gold` victory accent when something is won. It never comes from extra colors or decoration.
2. **Two densities, on purpose.** Every screen is either *roomy* or *dense* (see Layout). Choose one per screen and stick to it.
3. **Never color alone.** Run states, types and feedback always show a word or an icon as well as a color.
4. **Second monitor and phone are equal.** Design phone first, then let the layout grow at `bp-tablet`, `bp-desktop` and `bp-wide`.

## Voice and content

- Talk like a fellow Nuzlocker: short, warm and direct. "Add encounter", "Mark as fainted", "Nice — 8 badges!" Celebrate wins and treat losses gently ("Rest easy, Ziggy").
- Use sentence case everywhere: "Box selection", not "Box Selection". Use all caps only in the `overline` style.
- Address the player as "you". Write "Pokémon" with the é. Use game terms people already know: encounter, box, faint, level cap, gym.
- Write numbers as digits ("Lv 23", "3 deaths"), and use the ` · ` separator for metadata ("Lv 14 · Adamant · Intimidate").
- No emoji in UI chrome. Players' own run names and notes can include anything.

## Color

- Page ground is `canvas`. Content sits on `surface` cards. Use `surface-raised` for anything floating and `surface-sunken` for wells (search fields, empty slots, table headers).
- Text: `ink` for primary, `ink-muted` for secondary, `ink-subtle` only for placeholders on `surface`. Every text token meets 4.5:1 on the grounds its note names, in both themes.
- **Emerald is the brand.** Use `emerald` fills with `on-emerald` text for the primary action and the selected state. Use `emerald-strong` for green text and links. `emerald-soft` tints selections. `emerald-deep` is the dark "shader" green for hero bands and the run banner, with `on-emerald-deep` text. `emerald-sheen` is the reflective highlight: a thin top edge, a progress fill or a sparkle on `emerald-deep`. Never use it as text on light surfaces.
- Use at most one `emerald` primary button per view.
- `gold` belongs to victories only: badges, champion cleared, personal bests. Its text partner is `on-gold`, and gold text on cards is `gold-strong`.
- Feedback: `danger`, `warning` and `info` for text and icons, each with a `-soft` banner background. Destructive actions use `danger`. Never use red to mean "fainted"; that has its own state.
- `focus` is the keyboard focus ring: 2px solid with a 2px offset on every interactive element. It is blue so it never disappears against emerald.

### Run states

Every Pokémon in a run has one state. Always show it as a **chip with icon plus word**, or as an icon with a tooltip in very dense cells. Each state has a background token and an `-ink` text token.

| State | Chip | Ink | Icon (`assets/StateIcons`) | Meaning |
|---|---|---|---|---|
| Alive | `state-alive` | `state-alive-ink` | `alive.svg` (heart-pulse) | On the team or available |
| Fainted | `state-fainted` | `state-fainted-ink` | `fainted.svg` (skull) | Dead. The run's permanent loss |
| Boxed | `state-boxed` | `state-boxed-ink` | `boxed.svg` (archive) | Alive, stored in the PC |
| Caught | `state-caught` | `state-caught-ink` | `caught.svg` (circle-check) | New catch, not yet placed |
| Missed | `state-missed` | `state-missed-ink` | `missed.svg` (circle-slash) | Encounter failed or skipped |
| Gift | `state-gift` | `state-gift-ink` | `gift.svg` (gift) | Received as a gift |
| Trade | `state-trade` | `state-trade-ink` | `trade.svg` (arrow-left-right) | Received in an in-game trade |

Fainted is the only **dark** chip, and alive is light in both themes. That way the two never rely on red against green, which colorblind players can't tell apart, and a loss reads with weight. In a team grid, a fainted mon's slot also shows its sprite in grayscale at 55% opacity. Its text stays full strength.

### Pokémon types

`type-normal` … `type-fairy` are badge fills and look the same in both themes. Put `type-on-dark` text on light fills and `type-on-light` text on dark fills, as each token's note says. Every pair is at least 5.3:1. Always print the type name in the badge. Use type colors only where a type is shown, never as decoration or a page accent.

## Typography

- One family: **Plus Jakarta Sans** (`--font-sans`, files in `fonts/`, weights 400–800). It's rounded and friendly without looking childish.
- Display: `display` (home hero, run complete), `title-1` (page title), `title-2` (section), `title-3` (card title).
- Text: `body` on roomy screens, `body-dense` on dense screens, `label` for buttons, tabs, chips and form labels, `caption` for metadata, `overline` for eyebrows.
- **Numbers line up.** Anything numeric — levels, HP, stats, damage %, counts — uses `font-variant-numeric: tabular-nums`. With it, every digit is the same width, so a column of levels (5, 14, 100) aligns on the right and numbers don't shift as they count up. Use `stat` for big stat-tile numbers and `data` for table numbers, right-aligned.
- On phones, inputs are at least 16px so iOS doesn't zoom in on tap.

## Layout and density

| | Roomy | Dense |
|---|---|---|
| Used for | Home, search and browse runs, box view, single-task screens, settings | Fight planner, box selection, encounter and stat tables |
| Body text | `body` | `body-dense` |
| Card padding | `space-5` | `space-3` |
| Gap between cards | `space-6` | `space-4` |
| Rows | `row-roomy` | `row-dense` |
| Controls | `control-md` (`control-touch` on phones) | `control-sm` on desktop, `control-touch` on phones |

- Roomy screens show the core task and simple navigation. Put secondary actions in a menu.
- Content max width is `content-max`, centered. Page gutter is `space-4` on phones and `space-6` from `bp-tablet` up.
- Navigation: a bottom tab bar on phones, top tabs from `bp-tablet` up.
- Phones get no hover-only actions. Everything reachable by hover is also reachable by tap.

## Shape and depth

- Soft and rounded: `radius-lg` cards, `radius-md` buttons and box slots, `radius-sm` inputs and type badges, `radius-pill` chips, search and toggles, `radius-xl` dialogs and sheets.
- Cards lift: `shadow-1` at rest, `shadow-2` on hover or selected, `shadow-3` for menus and popovers, `shadow-4` for dialogs. In dark theme the shadows carry a faint top highlight for the reflective sheen.
- Cards have no outline in light theme (shadow only). In dark theme use a `line` hairline, because shadows read weakly on dark grounds.

## Motion

- Default 160ms ease-out for hovers and presses. 240ms for menus and sheets entering.
- Cards rise 2px on hover (`shadow-1` to `shadow-2`). Buttons press down 1px.
- One celebratory moment: when a badge or a run is won, a 600ms `emerald-sheen` and `gold` sparkle. Nowhere else.
- Respect `prefers-reduced-motion`: drop movement and keep color changes.

## Iconography

- **Lucide** (ISC licence), 2px stroke, round caps, at `icon-sm` (16px) and `icon-md` (20px). Icons take the color of their text.
- Run-state icons are copied from Lucide 0.460.0 into `assets/StateIcons`. Use inline SVG in code so they inherit `currentColor`.
- Pokémon sprites come from the game data and show at `sprite-sm` or `sprite-lg`, with `image-rendering: pixelated` for pixel sprites.
- Don't use Pokémon logos, the Poké Ball or official art as nuzhub's branding.

## Logo

There's no logo yet. Set the name as the wordmark: **nuzhub**, all lowercase, Plus Jakarta Sans 800, letter-spacing -0.02em, in `emerald` (or `on-emerald-deep` on `emerald-deep`).

## Credits

Plus Jakarta Sans © The Plus Jakarta Sans Project Authors, SIL Open Font License 1.1. Icons © Lucide Contributors, ISC License. Pokémon type colors follow the community-standard palette. Pokémon is a trademark of Nintendo / Creatures / GAME FREAK, and nuzhub is a fan project.
