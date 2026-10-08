# Card

The basic surface: a `surface` panel at `radius-lg` that lifts off `canvas` with `shadow-1`.

- Padding is `space-5` on roomy screens and `space-3` (`nz-card-dense`) on dense ones.
- Clickable cards (`is-interactive`) rise 2px to `shadow-2` on hover. The whole card is the link.
- **Featured** (`nz-card-featured`): `emerald-deep` with a 2px `emerald-sheen` top edge, for one moment per screen: current run, run complete, a new personal best.
- Dark theme adds a `line` hairline, because shadows read weakly there.
- Don't put a colored accent bar on the left edge, and don't nest cards inside cards.
- The consumer provides the title, meta line and body content.
