"""How likely is a board to be hit with a given amount of gold?

A hit is buying every copy a player still needs. Each roll shows SHOP_SLOTS units; a slot
picks a cost by the level's shop odds, then a unit uniformly among that cost's copies left in
the pool. The state is the probability of every combination of copies bought so far (one array
axis per target unit), stepped one slot at a time, so units of the same cost deplete the same
pool. Gold buys the copies first (cost x copies); what is left rolls at 2 gold each.

The walk keeps the odds after every roll (the curve the web app draws), and the odds at the
amounts of gold asked for are read from it.
"""

from dataclasses import dataclass

import numpy as np

SHOP_ODDS_PER_LEVEL = {
    2: {1: 1, 2: 0, 3: 0, 4: 0, 5: 0},
    3: {1: 0.75, 2: 0.25, 3: 0, 4: 0, 5: 0},
    4: {1: 0.55, 2: 0.30, 3: 0.15, 4: 0, 5: 0},
    5: {1: 0.45, 2: 0.33, 3: 0.20, 4: 0.02, 5: 0},
    6: {1: 0.30, 2: 0.40, 3: 0.25, 4: 0.05, 5: 0},
    7: {1: 0.16, 2: 0.30, 3: 0.43, 4: 0.10, 5: 0.01},
    8: {1: 0.15, 2: 0.20, 3: 0.32, 4: 0.30, 5: 0.03},
    9: {1: 0.10, 2: 0.17, 3: 0.25, 4: 0.33, 5: 0.15},
    10: {1: 0.05, 2: 0.10, 3: 0.20, 4: 0.40, 5: 0.25},
    11: {1: 0.01, 2: 0.02, 3: 0.12, 4: 0.50, 5: 0.35},
}
POOL_SIZES_INDIVIDUAL = {1: 30, 2: 25, 3: 18, 4: 10, 5: 9}
POOL_SIZES_TOTAL = {1: 420, 2: 325, 3: 252, 4: 140, 5: 90}

SHOP_SLOTS = 5
ROLL_COST = 2
DEFAULT_GOLD = (50, 60, 70, 80, 90, 100)
MAX_GOLD = 300
# The curve runs until the board is this likely, but covers at least this much gold
CURVE_TARGET = 0.95
CURVE_MIN_GOLD = 100
# Largest joint state the walk will hold: the product of (copies + 1) over the targets
MAX_STATES = 200_000


@dataclass(frozen=True)
class RollTarget:
    """A unit the board needs: `copies` more to buy, with `copies_out` of its own already gone."""

    name: str
    cost: int
    copies: int
    copies_out: int = 0


def calculate_roll_odds(
    level: int,
    targets: list[RollTarget],
    gold: list[int] | tuple[int, ...] = DEFAULT_GOLD,
    tier_out: dict[int, int] | None = None,
) -> dict:
    """The odds of buying every target's copies, for each amount of gold.

    `tier_out` maps a cost to the copies of that cost gone from the pool that aren't the
    targets' own (those are `copies_out`). Returns `results`, in the order of `gold`, and
    `curve`. Both hold dicts of `gold`, `rolls` (what is left after buying the copies, at 2
    gold each), `all_units` and `per_unit` (name -> the odds of that unit's copies alone).
    The curve has a point after every roll, from the gold that buys the copies up to the
    first point at CURVE_TARGET, and covers at least CURVE_MIN_GOLD and every amount of gold
    asked for, though never more than MAX_GOLD; each of its points is the gold actually spent.
    """
    tier_out = tier_out or {}
    validate(level, targets, gold, tier_out)
    shape = tuple(t.copies + 1 for t in targets)
    goal = tuple(t.copies for t in targets)
    hit_odds, stay = slot_odds(level, targets, tier_out, shape)

    spend = sum(t.cost * t.copies for t in targets)
    rolls_for = {g: max(0, g - spend) // ROLL_COST for g in gold}
    last_roll = max(0, MAX_GOLD - spend) // ROLL_COST
    required = max(max(rolls_for.values()), max(0, CURVE_MIN_GOLD - spend) // ROLL_COST)

    dist = np.zeros(shape)
    dist[(0,) * len(targets)] = 1.0
    curve = [snapshot(dist, targets, goal, spend, 0)]
    while len(curve) - 1 < last_roll and (
        len(curve) - 1 < required or float(dist[goal]) < CURVE_TARGET
    ):
        for _ in range(SHOP_SLOTS):
            dist = step_slot(dist, hit_odds, stay)
        curve.append(snapshot(dist, targets, goal, spend, len(curve)))
    results = [{**curve[rolls_for[g]], "gold": g} for g in gold]
    return {"results": results, "curve": curve}


def snapshot(
    dist: np.ndarray, targets: list[RollTarget], goal: tuple[int, ...], spend: int, rolls: int
) -> dict:
    """The odds after `rolls` rolls."""
    return {
        "gold": spend + ROLL_COST * rolls,
        "rolls": rolls,
        "all_units": round(float(dist[goal]), 4),
        "per_unit": {
            t.name: round(float(marginal(dist, axis, t.copies)), 4)
            for axis, t in enumerate(targets)
        },
    }


def validate(
    level: int,
    targets: list[RollTarget],
    gold: list[int] | tuple[int, ...],
    tier_out: dict[int, int],
) -> None:
    """Raise ValueError, with a message the model can act on, for input that has no answer."""
    if level not in SHOP_ODDS_PER_LEVEL:
        raise ValueError(f"level must be between 2 and 11, not {level}")
    if not targets:
        raise ValueError("units must name at least one unit")
    if len({t.name for t in targets}) != len(targets):
        raise ValueError("each unit may appear only once; add its copies together")
    states = 1
    for t in targets:
        if t.cost not in POOL_SIZES_INDIVIDUAL:
            raise ValueError(f"{t.name}: cost must be between 1 and 5, not {t.cost}")
        if t.copies < 1:
            raise ValueError(f"{t.name}: copies must be at least 1")
        if not 0 <= t.copies_out <= POOL_SIZES_INDIVIDUAL[t.cost]:
            raise ValueError(
                f"{t.name}: copies_out must be between 0 and {POOL_SIZES_INDIVIDUAL[t.cost]}"
            )
        states *= t.copies + 1
    if states > MAX_STATES:
        raise ValueError("too many units and copies to calculate; ask for fewer units")
    for cost, out in tier_out.items():
        if cost not in POOL_SIZES_TOTAL:
            raise ValueError(f"tier_out: cost must be between 1 and 5, not {cost}")
        gone = out + sum(t.copies_out for t in targets if t.cost == cost)
        if out < 0 or gone > POOL_SIZES_TOTAL[cost]:
            raise ValueError(
                f"tier_out: more {cost}-cost copies gone than the pool's {POOL_SIZES_TOTAL[cost]}"
            )
    if not gold:
        raise ValueError("gold must list at least one amount")
    if any(not 0 <= g <= MAX_GOLD for g in gold):
        raise ValueError(f"gold must be between 0 and {MAX_GOLD}")


def slot_odds(
    level: int,
    targets: list[RollTarget],
    tier_out: dict[int, int],
    shape: tuple[int, ...],
) -> tuple[list[np.ndarray], np.ndarray]:
    """For every state, the odds that one slot shows (and buys) each target, and that it shows none."""
    bought = np.indices(shape)
    # Same-cost targets draw from one pool, so each cost's copies left depend on all of them
    bought_by_cost: dict[int, np.ndarray] = {}
    for axis, t in enumerate(targets):
        bought_by_cost[t.cost] = bought_by_cost.get(t.cost, 0) + bought[axis]
    hits = []
    for axis, t in enumerate(targets):
        cost_gone = tier_out.get(t.cost, 0) + sum(
            o.copies_out for o in targets if o.cost == t.cost
        )
        cost_left = POOL_SIZES_TOTAL[t.cost] - cost_gone - bought_by_cost[t.cost]
        unit_left = POOL_SIZES_INDIVIDUAL[t.cost] - t.copies_out - bought[axis]
        needed = bought[axis] < t.copies
        hits.append(cell_odds_calculation(level, t.cost, unit_left, cost_left) * needed)
    return hits, 1 - sum(hits)


def cell_odds_calculation(level: int, target_unit_cost: int, unit_left, cost_left):
    """The odds that one shop slot shows one particular unit: the odds of its cost, times its
    share of the copies of that cost left. Works on numbers or arrays of them.
    """
    tier_odds = SHOP_ODDS_PER_LEVEL[level][target_unit_cost]
    share = np.maximum(unit_left, 0) / np.maximum(cost_left, 1)
    return tier_odds * np.minimum(share, 1)


def step_slot(dist: np.ndarray, hit_odds: list[np.ndarray], stay: np.ndarray) -> np.ndarray:
    """The distribution after one more shop slot."""
    new = dist * stay
    for axis, odds in enumerate(hit_odds):
        src = [slice(None)] * dist.ndim
        dst = [slice(None)] * dist.ndim
        src[axis], dst[axis] = slice(0, -1), slice(1, None)
        # Nothing flows out of the goal index: a unit's odds are 0 once all its copies are bought
        new[tuple(dst)] += (dist * odds)[tuple(src)]
    return new


def marginal(dist: np.ndarray, axis: int, goal: int) -> float:
    """The odds that `axis`'s unit has all its copies, whatever the others have."""
    return dist.take(goal, axis=axis).sum()
