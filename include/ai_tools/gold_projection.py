"""How much gold, XP and Free Rolls has a player earned by a given round?

A projection walks the rounds from the start (2-1 by default) to the end round, once for each
Streak Scenario: every PvP fight won, every one lost, and a mix. It reports what the player can
spend in the end round's planning phase, before that round's fight, so the end round's own
result is left out. Nothing is spent along the way, so interest is as high as it can be and
every gold figure is a ceiling, not a forecast; HP is not modelled either, so win and loss
are bounds on income rather than likely games.

A round's income reaches the planning phase in this order: interest on the balance carried
in, passive income, the reward of the round before (neutrals, carousel, or the win and streak
gold of a fight), then the gold of an augment taken that round. Streak gold follows the real
run of PvP results, which carousels and neutrals never break. The mixed scenario picks 2 or 3
PvP rounds per stage at random as wins, so it is averaged over seeded runs: the same input
always gives the same answer.

The XP needed per level is the real table. The other rules are PLACEHOLDERS until the
current set's values are confirmed (natural XP per round, streak gold, win gold, the round
rewards and the arrival state at 2-1); replace them before this is served to users. The tests
pass their own Rules and do not depend on any of them.
"""

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from ai_tools.roll_odds import ROLL_COST

ROUNDS_PER_STAGE = 7
CAROUSEL_ROUND = 4
NEUTRAL_ROUND = 7
FIRST_ROUND = (2, 1)
# The latest and earliest rounds a projection may end on
EARLIEST_END = (2, 2)
LATEST_END = (5, 2)
AUGMENT_SLOTS = ((2, 1), (3, 2), (4, 2))
DEFAULT_END = "4-2"
LEVEL_TARGETS = (8, 9)
MAX_GOLD = 500

# How many times the mixed scenario is drawn, and the seed that makes the draws repeatable
MIXED_RUNS = 400
MIXED_SEED = 18

AUGMENTS_PATH = Path(__file__).with_name("augments.json")

Round = tuple[int, int]


@dataclass(frozen=True)
class Rules:
    """The game's income and leveling rules. Only the XP table is confirmed; the rest are
    placeholders, see the module doc."""

    passive_first: int = 4  # passive gold at 2-1
    passive: int = 5  # and from 2-2 on
    neutral_gold: int = 6  # paid after a neutral round, on average
    carousel_gold: int = 3  # paid after a carousel, on average
    win_gold: int = 1  # for winning a PvP fight
    # (streak length at least, gold), ascending; a streak pays the last tier it reached
    streak_tiers: tuple[tuple[int, int], ...] = ((2, 1), (4, 2), (5, 3))
    interest_per: int = 10  # 1 gold of interest per this much gold held
    interest_cap: int = 5
    natural_xp: int = 2  # per round, every round
    # XP needed to go from this level to the next (confirmed)
    xp_to_level_up: dict[int, int] = field(
        default_factory=lambda: {
            1: 2,
            2: 2,
            3: 6,
            4: 10,
            5: 20,
            6: 36,
            7: 56,
            8: 68,
            9: 68,
        }
    )
    buy_xp: int = 4  # XP bought at a time...
    buy_xp_gold: int = 4  # ...for this much gold
    # Arrival at 2-1
    start_level: int = 3
    start_xp: int = 0
    start_gold: int = 0


RULES = Rules()


@dataclass(frozen=True)
class Augment:
    """An augment of the masterlist and what it adds, as one flat effect."""

    name: str
    gold: int = 0  # once, in the round it is taken
    free_rolls: int = 0  # once, in the round it is taken
    xp_per_round: int = 0  # every round from the one it is taken in
    max_interest: int = 0  # added to the interest cap from the round it is taken in


@dataclass(frozen=True)
class AugmentPick:
    """An augment taken at one of the three slots."""

    augment: Augment
    slot: Round


@dataclass(frozen=True)
class Start:
    """What the player has on arriving at `round`, before that round's income.

    `streak` is a streak already running: positive for wins, negative for losses.
    """

    round: Round = FIRST_ROUND
    level: int = RULES.start_level
    xp: int = RULES.start_xp
    gold: int = RULES.start_gold
    streak: int = 0


def load_augments(path: Path = AUGMENTS_PATH) -> dict[str, Augment]:
    """The masterlist, by name."""
    return {entry["name"]: Augment(**entry) for entry in json.loads(path.read_text())}


def parse_round(text: str) -> Round:
    match = re.fullmatch(r"\s*(\d+)-(\d+)\s*", text or "")
    if not match or not 1 <= int(match[2]) <= ROUNDS_PER_STAGE:
        raise ValueError(
            f"round must look like 4-2, with a round from 1 to 7, not {text!r}"
        )
    return int(match[1]), int(match[2])


def name_round(rnd: Round) -> str:
    return f"{rnd[0]}-{rnd[1]}"


def round_kind(rnd: Round) -> str:
    return {CAROUSEL_ROUND: "carousel", NEUTRAL_ROUND: "neutral"}.get(rnd[1], "pvp")


def rounds_between(start: Round, end: Round) -> list[Round]:
    """Every round from `start` to `end`, both included."""
    rounds, rnd = [], start
    while rnd <= end:
        rounds.append(rnd)
        rnd = (rnd[0], rnd[1] + 1) if rnd[1] < ROUNDS_PER_STAGE else (rnd[0] + 1, 1)
    return rounds


def calculate_gold_projection(
    end_round: str = DEFAULT_END,
    augments: list[AugmentPick] | None = None,
    start: Start | None = None,
    rules: Rules = RULES,
    runs: int = MIXED_RUNS,
) -> dict:
    """Gold, XP and Free Rolls by the end round, for the win, mixed and loss Streak Scenarios.

    Returns `end_round`, `start`, the `level_curve` (every level from the start's to the last
    target: the XP it takes, the round the XP reaches it by itself if it does, and what is
    still missing and costs at the end round; XP doesn't depend on the fights, so there is one
    curve) and, for each scenario under `scenarios`: `gold`, `free_rolls`, `free_roll_gold`
    (the Free Rolls at what a roll costs) and `total_gold` (both together), `natural_xp`,
    `augment_xp`, the `level` the XP reaches by itself, `levels` (for each target level, the XP
    still missing, the gold that buys it in whole purchases and the `leftover` to roll with
    after paying, Free Rolls included, negative for a shortfall of gold) and a `series` of the
    same totals at every round's planning
    phase, with that round's `kind`, `level` and `income`, which the page charts. Raises
    ValueError for input with no answer.
    """
    start = start or Start()
    augments = list(augments or [])
    end = parse_round(end_round)
    validate(end, augments, start, rules, runs)
    rounds = rounds_between(start.round, end)
    pvp = [rnd for rnd in rounds[:-1] if round_kind(rnd) == "pvp"]

    scenarios = {
        "win": simulate(rounds, dict.fromkeys(pvp, True), start, augments, rules),
        "loss": simulate(rounds, dict.fromkeys(pvp, False), start, augments, rules),
        "mixed": mixed(rounds, pvp, start, augments, rules, runs),
    }
    summaries = {
        name: summarise(scenarios[name], start, rules)
        for name in ("win", "mixed", "loss")
    }
    return {
        "end_round": name_round(end),
        "start": {
            "round": name_round(start.round),
            "level": start.level,
            "xp": start.xp,
            "gold": start.gold,
            "streak": start.streak,
        },
        "level_curve": level_curve(summaries["win"], start, rules),
        "scenarios": summaries,
    }


def validate(
    end: Round, augments: list[AugmentPick], start: Start, rules: Rules, runs: int
) -> None:
    """Raise ValueError, with a message the model can act on, for input that has no answer."""
    if not EARLIEST_END <= end <= LATEST_END:
        raise ValueError(
            f"end_round must be between {name_round(EARLIEST_END)} and {name_round(LATEST_END)}, "
            f"not {name_round(end)}"
        )
    if not FIRST_ROUND <= start.round < end:
        raise ValueError(
            f"start_round must be from {name_round(FIRST_ROUND)} and before {name_round(end)}"
        )
    if start.level not in rules.xp_to_level_up:
        raise ValueError(
            f"start_level must be between 1 and {max(rules.xp_to_level_up)}"
        )
    if not 0 <= start.xp < rules.xp_to_level_up[start.level]:
        raise ValueError(
            f"start_xp must be between 0 and {rules.xp_to_level_up[start.level] - 1} at level {start.level}"
        )
    if not 0 <= start.gold <= MAX_GOLD:
        raise ValueError(f"start_gold must be between 0 and {MAX_GOLD}")
    if runs < 1:
        raise ValueError("runs must be at least 1")
    slots = [pick.slot for pick in augments]
    if len(set(slots)) != len(slots):
        raise ValueError("take at most one augment at each slot")
    for pick in augments:
        if pick.slot not in AUGMENT_SLOTS:
            allowed = ", ".join(name_round(s) for s in AUGMENT_SLOTS)
            raise ValueError(f"an augment's slot must be one of {allowed}")
        if pick.slot > end:
            raise ValueError(
                f"{pick.augment.name}: slot {name_round(pick.slot)} comes after the end round"
            )


def mixed(
    rounds: list[Round],
    pvp: list[Round],
    start: Start,
    augments: list[AugmentPick],
    rules: Rules,
    runs: int,
) -> list[dict]:
    """The mixed scenario: each stage's wins are 2 or 3 of its PvP rounds at random, and the
    runs are averaged. Only gold depends on the results, so the other totals are the same in
    every run."""
    rng = random.Random(MIXED_SEED)
    by_stage: dict[int, list[Round]] = {}
    for rnd in pvp:
        by_stage.setdefault(rnd[0], []).append(rnd)
    all_runs = []
    for _ in range(runs):
        wins = dict.fromkeys(pvp, False)
        for stage_rounds in by_stage.values():
            count = rng.choice((2, 3))
            for rnd in rng.sample(stage_rounds, min(count, len(stage_rounds))):
                wins[rnd] = True
        all_runs.append(simulate(rounds, wins, start, augments, rules))
    series = [dict(point) for point in all_runs[0]]
    for i, point in enumerate(series):
        point["gold"] = sum(run[i]["gold"] for run in all_runs) / runs
        point["income"] = {
            source: round(sum(run[i]["income"][source] for run in all_runs) / runs, 1)
            for source in point["income"]
        }
    return series


def simulate(
    rounds: list[Round],
    wins: dict[Round, bool],
    start: Start,
    augments: list[AugmentPick],
    rules: Rules,
) -> list[dict]:
    """Walk the rounds with every PvP fight (but the last round's) decided by `wins`.

    Returns the totals at each round's planning phase, before spending, with `gold` the whole
    balance, `income` what that round added to it by source, and the rest running totals
    since the start.
    """
    gold, free_rolls, natural_xp, augment_xp = start.gold, 0, 0, 0
    streak, reward = start.streak, 0
    series = []
    for rnd in rounds:
        taken = [pick.augment for pick in augments if pick.slot <= rnd]
        cap = rules.interest_cap + sum(a.max_interest for a in taken)
        interest = min(gold // rules.interest_per, cap)
        passive = rules.passive_first if rnd == FIRST_ROUND else rules.passive
        new_picks = [pick.augment for pick in augments if pick.slot == rnd]
        augment_gold = sum(a.gold for a in new_picks)
        gold += interest + passive + reward + augment_gold
        natural_xp += rules.natural_xp
        augment_xp += sum(a.xp_per_round for a in taken)
        free_rolls += sum(a.free_rolls for a in new_picks)
        kind = round_kind(rnd)
        series.append(
            {
                "round": name_round(rnd),
                "kind": kind,
                "gold": gold,
                "natural_xp": natural_xp,
                "augment_xp": augment_xp,
                "free_rolls": free_rolls,
                "income": {
                    "interest": interest,
                    "passive": passive,
                    "reward": reward,
                    "augment": augment_gold,
                },
            }
        )
        reward = 0
        if kind == "neutral":
            reward = rules.neutral_gold
        elif kind == "carousel":
            reward = rules.carousel_gold
        elif rnd in wins:
            won = wins[rnd]
            streak = (max(streak, 0) + 1) if won else (min(streak, 0) - 1)
            reward = (rules.win_gold if won else 0) + streak_gold(abs(streak), rules)
    return series


def streak_gold(length: int, rules: Rules) -> int:
    """The gold a streak of `length` fights pays."""
    return max(
        (gold for needed, gold in rules.streak_tiers if length >= needed), default=0
    )


def summarise(series: list[dict], start: Start, rules: Rules) -> dict:
    """The end totals of a scenario, what its XP buys, and the series rounded for display,
    with the level each round's XP reaches."""
    series = [
        {
            **point,
            "gold": round(point["gold"]),
            "free_roll_gold": point["free_rolls"] * ROLL_COST,
            "total_gold": round(point["gold"]) + point["free_rolls"] * ROLL_COST,
            "level": level_after(
                start, point["natural_xp"] + point["augment_xp"], rules
            )[0],
        }
        for point in series
    ]
    last = series[-1]
    level, xp = level_after(start, last["natural_xp"] + last["augment_xp"], rules)
    levels = {}
    for target in LEVEL_TARGETS:
        missing = xp_missing(level, xp, target, rules)
        cost = xp_cost(missing, rules)
        levels[str(target)] = {
            "xp_missing": missing,
            "gold_cost": cost,
            "leftover": leftover(last["gold"], cost, last["free_roll_gold"]),
        }
    return {
        "gold": last["gold"],
        "free_roll_gold": last["free_roll_gold"],
        "total_gold": last["total_gold"],
        "natural_xp": last["natural_xp"],
        "augment_xp": last["augment_xp"],
        "free_rolls": last["free_rolls"],
        "level": level,
        "levels": levels,
        "series": series,
    }


def leftover(gold: int, cost: int, free_roll_gold: int) -> int:
    """What is left to roll with after buying a level: the gold left plus the Free Rolls, at
    what a roll costs. Free Rolls can't buy XP, so a shortfall is in gold alone (negative)."""
    return gold - cost + free_roll_gold if gold >= cost else gold - cost


def level_curve(scenario: dict, start: Start, rules: Rules) -> list[dict]:
    """Every level from the start's to the last target: `xp` to reach it from the level below,
    `total_xp` from the start, `reached_at` (the round the XP alone reaches it, or None), and
    the `xp_missing` at the end round with the `gold_cost` that buys it."""
    last = scenario["series"][-1]
    level, xp = level_after(start, last["natural_xp"] + last["augment_xp"], rules)
    curve, total = [], -start.xp
    for below in range(start.level, LEVEL_TARGETS[-1]):
        target = below + 1
        total += rules.xp_to_level_up[below]
        missing = xp_missing(level, xp, target, rules)
        curve.append(
            {
                "level": target,
                "xp": rules.xp_to_level_up[below],
                "total_xp": total,
                "reached_at": next(
                    (p["round"] for p in scenario["series"] if p["level"] >= target),
                    None,
                ),
                "xp_missing": missing,
                "gold_cost": xp_cost(missing, rules),
            }
        )
    return curve


def level_after(start: Start, earned_xp: int, rules: Rules) -> tuple[int, int]:
    """The level and the XP towards the next, once `earned_xp` is added to the start."""
    level, xp = start.level, start.xp + earned_xp
    while level in rules.xp_to_level_up and xp >= rules.xp_to_level_up[level]:
        xp -= rules.xp_to_level_up[level]
        level += 1
    return level, xp


def xp_missing(level: int, xp: int, target: int, rules: Rules) -> int:
    """The XP still needed to reach `target` from `level` with `xp` towards the next."""
    if level >= target:
        return 0
    return sum(rules.xp_to_level_up[lvl] for lvl in range(level, target)) - xp


def xp_cost(missing: int, rules: Rules) -> int:
    """The gold that buys `missing` XP, in whole purchases."""
    return -(-missing // rules.buy_xp) * rules.buy_xp_gold
