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

**Tier**:
The breakpoint an active trait reached on a board, counted from 1.

**Style**:
How an active trait looks in game at a Tier: bronze, silver, gold, prismatic or unique.
_Avoid_: rank, medal, colour

**Totals**:
Exact per-patch counts (boards, matches, placement sum, top 4s, wins) kept for an entity such as a unit, item, trait or comp; never rates.
_Avoid_: counters, counter tables

**Stats**:
Rates and deltas derived from Totals, never stored.

**Unit**:
A champion a player fields. Costs 1 to 5 gold, and a Board holds several.

**Copy**:
One purchasable instance of a Unit. Three Copies make a 2-star, nine a 3-star.

**Pool**:
The Copies of every Unit that one lobby's players share. Each Unit has a fixed number of Copies by cost, and a Copy bought leaves the Pool until it is sold.

**Shop**:
The five Units a player is offered at once, drawn from the Pool by the odds of the player's level.

**Roll**:
Paying 2 gold to redraw the Shop.

**Hit**:
Buying every Copy a Board still needs. Roll odds say how likely a Hit is at an amount of gold.
_Avoid_: find, land

**Round**:
One step of a game, named by its Stage and place in it, such as 4-2: a PvP fight, a carousel or neutrals.

**Stage**:
A numbered block of seven Rounds; the first number in a Round's name.

**Streak**:
Consecutive PvP fights all won or all lost, which pays extra gold. Carousels and neutrals do not break it.

**Interest**:
Bonus gold paid each Round for the gold a player holds, up to a cap that some augments raise.

**Free Roll**:
A Roll an augment grants, which costs no gold.
_Avoid_: reroll

**XP**:
What levels a player up: earned each Round, granted by augments, or bought with gold.
_Avoid_: exp

**Projection**:
The gold, XP and Free Rolls a player has by a Round under each Scenario; with nothing spent, the gold is a ceiling.

**Scenario**:
One way a Projection's Rounds go: which PvP fights are won or lost, and what is spent or gained each Round. The presets are win (every fight won), loss (every one lost) and mixed (some of each, averaged), with nothing spent.
_Avoid_: line, path, streak scenario

**Conversation**:
One /ask thread, from its first question until the visitor starts a new chat. Anonymous: it names no person.

**Turn**:
One question in a Conversation and the agent's answer, or its failure.
