# Button

Buttons trigger actions. Use **primary** (`emerald` fill, `on-emerald` text) at most once per view, for the thing the screen is for.

- Variants: primary (`nz-btn-primary`), default outlined (`nz-btn`), ghost for low-weight actions like "View all" (`nz-btn-ghost`, `emerald-strong` text), and danger for destructive actions (`nz-btn-danger`). Always confirm a delete.
- Sizes: default is `control-md`. Small (`nz-btn-sm`, `control-sm`) is for dense desktop tables only. On phones, every button is at least `control-touch` tall.
- Labels are verb first and in sentence case: "Add encounter", "Mark as fainted". An optional leading Lucide icon goes at `icon-sm`.
- The consumer provides the label, the onClick handler and the variant.
