# Tactician Labs

TFT analytics: ranked matches are ingested, boards are grouped into comps, and win, top-4 and placement stats are derived per patch.

## Language

**Board**:
One player's final board in one match.

**Patch**:
A match's game version; Totals and Comps are kept per patch.

**Comp**:
A group of boards built around the same core units and carries, found by clustering a patch's boards.
_Avoid_: composition (outside table names), cluster, archetype

**Variant**:
A sub-group of one comp's boards that differs from it by a few units or traits.

**Base build**:
The boards of a comp that fit none of its variants.

**Assign**:
Put a board into its nearest comp, or leave it out if it is too dissimilar.
_Avoid_: classify

**Totals**:
Exact per-patch counts (boards, matches, placement sum, top 4s, wins) kept for an entity such as a unit, item, trait or comp; never rates.
_Avoid_: counters, counter tables

**Stats**:
Rates and deltas derived from Totals, never stored.
