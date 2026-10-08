# DataTable

The dense table for fight planning, box selection and encounter logs.

- Rows are `row-dense` with `body-dense` text. Headers are `overline` in `ink-muted` on `surface-sunken`.
- Numbers use the `data` style: tabular figures, right-aligned, header included.
- Hover rows to `surface-hover`. Selected rows use `emerald-soft`. Row dividers are `line` hairlines.
- On phones, keep the first column (the Pokémon) and the state. Move other columns into a tap-to-expand row or let the table scroll sideways inside its card.
- The consumer provides the columns (with numeric alignment), the rows, the selected row and sorting.
