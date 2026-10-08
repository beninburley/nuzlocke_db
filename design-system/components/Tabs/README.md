# Tabs

A segmented pill control that switches between views of the same run.

- The selected tab lifts onto `surface` with `shadow-1` and `emerald-strong` text. The others are `ink-muted` on `surface-sunken`.
- Use 2–6 tabs with short nouns. On phones, if the tabs don't fit, top-level navigation moves to a bottom tab bar and these tabs scroll sideways.
- Use `role="tablist"`/`"tab"` and `aria-selected`. Arrow keys move between tabs.
- The consumer provides the tab labels, the selected value and onChange.
