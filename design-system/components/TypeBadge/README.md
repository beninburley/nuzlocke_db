# TypeBadge

A small uppercase label in a Pokémon type's color, wherever typing is shown.

- Fill is `type-<name>`. Text is `type-on-dark` or `type-on-light`, as that token's note says. Every pair is at least 5.3:1 and identical in both themes.
- Always print the type name. Show dual types as two badges side by side with a `space-1` gap.
- Use type colors only for types, never as decoration.
- The consumer provides the type name.
