# TextField

Text inputs for forms, plus the pill-shaped search field used on browse screens.

- Always show a visible label (`label` style) above the field. Placeholders are examples, not labels.
- Help text goes below in `caption` and `ink-muted`. Errors replace the help text in `danger` and add `is-invalid` (a `danger` border). Say how to fix it: "Enter a number from 1 to 100".
- Fields use `radius-sm`, a `line-strong` border and a `surface` background. Search (`nz-search`) is `radius-pill` on `surface-sunken` at `control-touch` height.
- On phones, input text is 16px so iOS doesn't zoom.
- The consumer provides the label, value, onChange and an optional error message.
