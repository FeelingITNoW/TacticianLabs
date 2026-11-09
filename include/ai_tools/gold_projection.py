"""How much gold, XP and Free Rolls has a player earned by a given round?

A projection walks the rounds from the start (2-1 by default) to the end round, once for each
Scenario. A Scenario says which PvP fights are won or lost (every one, none, a seeded mix, or
a string of w and l, one letter per PvP fight) and, if it wants, what is spent or gained along
the way: gold by round (units bought, gold the masterlist doesn't hold), level targets by
round, and a line above which every spare 4 gold buys XP. The three presets, win, mixed and
loss, spend nothing, so interest is as high as it can be and their gold is a ceiling, not a
forecast; HP is not modelled either, so win and loss are bounds on income rather than likely
games. It reports what the player holds at the end round's planning phase, before that
round's fight, after the round's own spending.

A round's income reaches the planning phase in this order: interest on the balance carried
in, passive income, the reward of the round before (neutrals, carousel, or the win and streak
gold of a fight), then the gold of an augment taken that round. Then the round's own moves
happen in order: its gold entry, its level target and the XP bought above the line. Streak
gold follows the real run of PvP results, which carousels and neutrals never break. The mixed
scenario picks 2 or 3 PvP rounds per stage at random as wins, so it is averaged over seeded
runs: the same input always gives the same answer.

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
MAX_SCENARIOS = 3
PRESETS = ("win", "mixed", "loss")
PRESET_LABELS = {"win": "Win streak", "mixed": "Mixed", "loss": "Loss streak"}

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
            7: 60,
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


@dataclass(frozen=True)
class ScenarioPlan:
    """One Scenario asked for.

    `fights` is a preset (win, mixed or loss) or a string of w and l, one letter per PvP
    fight from the start round, never deciding the end round's own fight. `gold` is the gold
    each round gains (positive) or spends on units (negative); `levels` the level to be at
    after each round's gold entry; `level_above` a line above which each round buys XP with
    every spare 4 gold.
    """

    fights: str = "win"
    label: str | None = None
    gold: dict[Round, int] = field(default_factory=dict)
    levels: dict[Round, int] = field(default_factory=dict)
    level_above: int | None = None


class Overspend(ValueError):
    """A Scenario spends more gold than it holds."""

    def __init__(
        self,
        rnd: Round,
        what: str,
        held: int,
        needed: int,
        carried: list[tuple[str, int]],
        runs: int | None = None,
    ):
        self.round, self.what, self.held, self.needed = rnd, what, held, needed
        self.carried = carried
        balances = ", ".join(f"{name} {gold}" for name, gold in carried) or "none yet"
        lowest = f", lowest of the {runs} random runs" if runs else ""
        super().__init__(
            f"{what} at {name_round(rnd)} needs {needed} gold but only {held} is held. "
            f"Gold carried out of each earlier round{lowest}: {balances}"
        )


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


def next_round(rnd: Round) -> Round:
    return (rnd[0], rnd[1] + 1) if rnd[1] < ROUNDS_PER_STAGE else (rnd[0] + 1, 1)


def rounds_between(start: Round, end: Round) -> list[Round]:
    """Every round from `start` to `end`, both included."""
    rounds, rnd = [], start
    while rnd <= end:
        rounds.append(rnd)
        rnd = next_round(rnd)
    return rounds


def calculate_gold_projection(
    end_round: str | None = None,
    augments: list[AugmentPick] | None = None,
    start: Start | None = None,
    rules: Rules = RULES,
    runs: int = MIXED_RUNS,
    scenarios: list[ScenarioPlan] | None = None,
) -> dict:
    """Gold, XP and Free Rolls by the end round, for up to three Scenarios.

    Without `scenarios` it runs the win, mixed and loss presets with nothing spent. The end
    round is `end_round`, else the round after the last fight of the w/l strings (which must
    agree), else the default. Returns `end_round`, `start` and `scenarios`, a list with for
    each: its `label`, `preset` (or None) and `fights` (the w/l string, or None), the `gold`
    held after the end round's spending, `free_rolls`, `free_roll_gold` (the Free Rolls at
    what a roll costs) and `total_gold` (both together), `natural_xp`, `augment_xp`,
    `bought_xp`, the gold it `spent` on units, `gained` and spent on `leveling`, whether it is a
    `ceiling` (nothing spent), the `level` its XP reaches, `levels` (for each target level, the
    XP still missing, the gold that buys it in whole purchases and the `leftover` to roll with
    after paying, Free Rolls included, negative for a shortfall of gold), its `level_curve`
    (every level from the start's to the last target: the XP it takes, the round the XP reaches
    it if it does, and what is still missing and costs at the end round) and a `series` of the
    same totals at every round, with that round's `kind`, `level`, `income` and moves, which
    the page charts. Raises ValueError for input with no answer, and for a Scenario that
    spends more than it holds.
    """
    start = start or Start()
    augments = list(augments or [])
    plans = list(scenarios) if scenarios else [ScenarioPlan(preset) for preset in PRESETS]
    if len(plans) > MAX_SCENARIOS:
        raise ValueError(f"at most {MAX_SCENARIOS} scenarios, not {len(plans)}")
    end = resolve_end(end_round, plans, start)
    validate(end, augments, start, rules, runs)
    rounds = rounds_between(start.round, end)
    pvp = [rnd for rnd in rounds[:-1] if round_kind(rnd) == "pvp"]

    summaries = []
    for number, plan in enumerate(plans, 1):
        letters = fight_letters(plan)
        preset = plan.fights.strip().lower() if letters is None else None
        label = plan.label or (PRESET_LABELS[preset] if preset else f"Custom {number}")
        validate_plan(plan, label, rounds, rules)
        try:
            series = run_plan(plan, letters, rounds, pvp, start, augments, rules, runs)
        except Overspend as exc:
            raise ValueError(f"{label}: {exc}") from None
        summary = summarise(series, start, rules)
        summary["level_curve"] = level_curve(summary, start, rules)
        summaries.append({"label": label, "preset": preset, "fights": letters, **summary})
    return {
        "end_round": name_round(end),
        "start": {
            "round": name_round(start.round),
            "level": start.level,
            "xp": start.xp,
            "gold": start.gold,
            "streak": start.streak,
        },
        "scenarios": summaries,
    }


def fight_letters(plan: ScenarioPlan) -> str | None:
    """The plan's fights as a string of w and l, or None for a preset."""
    text = plan.fights.strip().lower()
    if text in PRESETS:
        return None
    letters = re.sub(r"\s", "", text)
    if not letters or set(letters) - {"w", "l"}:
        raise ValueError(
            "fights must be win, mixed, loss, or a string of w and l with one letter per "
            f"PvP fight, not {plan.fights!r}"
        )
    return letters


def resolve_end(end_round: str | None, plans: list[ScenarioPlan], start: Start) -> Round:
    """The end round: the one given, else the one the w/l strings agree on, else the default.

    A string's last letter is the fight before the end round, so the end round is the round
    after it. Raises ValueError when a string doesn't fit the end round, or two don't agree.
    """
    strings = [letters for plan in plans if (letters := fight_letters(plan))]
    latest = [
        rnd
        for rnd in rounds_between(start.round, LATEST_END)
        if round_kind(rnd) == "pvp" and next_round(rnd) <= LATEST_END
    ]
    if end_round:
        end = parse_round(end_round)
        fights = [r for r in rounds_between(start.round, end)[:-1] if round_kind(r) == "pvp"]
        for letters in strings:
            if len(letters) != len(fights):
                raise ValueError(
                    f"fights has {len(letters)} letters but {name_round(start.round)} to "
                    f"{name_round(end)} has {len(fights)} PvP fights: "
                    f"{', '.join(map(name_round, fights))}. Drop end_round to let the string "
                    "set it"
                )
        return end
    ends = {}
    for letters in strings:
        if len(letters) > len(latest):
            raise ValueError(
                f"fights has {len(letters)} letters but at most {len(latest)} PvP fights fit "
                f"between {name_round(start.round)} and {name_round(LATEST_END)}"
            )
        ends[letters] = next_round(latest[len(letters) - 1])
    if len(set(ends.values())) > 1:
        shown = ", ".join(f"{len(s)} letters end at {name_round(e)}" for s, e in ends.items())
        raise ValueError(f"the fight strings end at different rounds ({shown}); make them the same length")
    return next(iter(ends.values()), parse_round(DEFAULT_END))


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


def validate_plan(plan: ScenarioPlan, label: str, rounds: list[Round], rules: Rules) -> None:
    """Raise ValueError for a Scenario's moves that name no round of the projection or ask
    for a level or an amount of gold that doesn't exist."""
    top = max(rules.xp_to_level_up) + 1
    for kind, moves in (("gold", plan.gold), ("levels", plan.levels)):
        for rnd in moves:
            if rnd not in rounds:
                raise ValueError(
                    f"{label}: {kind} has round {name_round(rnd)}, but the projection runs "
                    f"{name_round(rounds[0])} to {name_round(rounds[-1])}"
                )
    for rnd, amount in plan.gold.items():
        if abs(amount) > MAX_GOLD:
            raise ValueError(f"{label}: gold at {name_round(rnd)} must be within {MAX_GOLD}")
    for rnd, target in plan.levels.items():
        if not 2 <= target <= top:
            raise ValueError(
                f"{label}: the level at {name_round(rnd)} must be from 2 to {top}, not {target}"
            )
    if plan.level_above is not None and not 0 <= plan.level_above <= MAX_GOLD:
        raise ValueError(f"{label}: level_above must be between 0 and {MAX_GOLD}")


def run_plan(
    plan: ScenarioPlan,
    letters: str | None,
    rounds: list[Round],
    pvp: list[Round],
    start: Start,
    augments: list[AugmentPick],
    rules: Rules,
    runs: int,
) -> list[dict]:
    """The series of one Scenario."""
    if letters is None and plan.fights.strip().lower() == "mixed":
        return mixed(rounds, pvp, start, augments, rules, runs, plan)
    if letters is None:
        wins = dict.fromkeys(pvp, plan.fights.strip().lower() == "win")
    else:
        wins = {rnd: letter == "w" for rnd, letter in zip(pvp, letters)}
    return simulate(rounds, wins, start, augments, rules, plan)


def mixed(
    rounds: list[Round],
    pvp: list[Round],
    start: Start,
    augments: list[AugmentPick],
    rules: Rules,
    runs: int,
    plan: ScenarioPlan,
) -> list[dict]:
    """The mixed scenario: each stage's wins are 2 or 3 of its PvP rounds at random, and the
    runs are averaged. Gold, and the XP a level line buys with it, depend on the results; the
    rest is the same in every run. A plan has to be affordable in every run."""
    rng = random.Random(MIXED_SEED)
    by_stage: dict[int, list[Round]] = {}
    for rnd in pvp:
        by_stage.setdefault(rnd[0], []).append(rnd)
    all_runs, failures, balances = [], [], []
    for _ in range(runs):
        wins = dict.fromkeys(pvp, False)
        for stage_rounds in by_stage.values():
            count = rng.choice((2, 3))
            for rnd in rng.sample(stage_rounds, min(count, len(stage_rounds))):
                wins[rnd] = True
        try:
            run = simulate(rounds, wins, start, augments, rules, plan)
        except Overspend as exc:
            failures.append(exc)
            balances.append(exc.carried)
            continue
        all_runs.append(run)
        balances.append([(p["round"], p["gold"]) for p in run])
    if failures:
        first = min(failures, key=lambda f: (f.round, f.held))
        lowest = [
            (name, min(b[i][1] for b in balances))
            for i, (name, _) in enumerate(first.carried)
        ]
        raise Overspend(first.round, first.what, first.held, first.needed, lowest, runs)
    series = [dict(point) for point in all_runs[0]]
    for i, point in enumerate(series):
        point["gold"] = sum(run[i]["gold"] for run in all_runs) / runs
        point["leveling"] = round(sum(run[i]["leveling"] for run in all_runs) / runs)
        point["bought_xp"] = round(sum(run[i]["bought_xp"] for run in all_runs) / runs)
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
    plan: ScenarioPlan,
) -> list[dict]:
    """Walk the rounds with every PvP fight (but the last round's) decided by `wins`.

    Returns the totals at each round's planning phase, after that round's spending, with
    `gold` the whole balance, `income` what that round added to it by source, `spent`,
    `gained` and `leveling` what its own moves did to it, and the rest running totals since
    the start. Raises Overspend when a move costs more than is held.
    """
    top = max(rules.xp_to_level_up) + 1
    gold, free_rolls, natural_xp, augment_xp, bought_xp = start.gold, 0, 0, 0, 0
    streak, reward = start.streak, 0
    series = []
    for rnd in rounds:
        carried = [(p["round"], p["gold"]) for p in series]
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

        entry = plan.gold.get(rnd, 0)
        if gold + entry < 0:
            raise Overspend(rnd, f"spending {-entry} gold", gold, -entry, carried)
        gold += entry
        leveling = 0
        target = plan.levels.get(rnd)
        if target is not None:
            level, xp = level_after(start, natural_xp + augment_xp + bought_xp, rules)
            cost = xp_cost(xp_missing(level, xp, target, rules), rules)
            if cost > gold:
                raise Overspend(rnd, f"reaching level {target}", gold, cost, carried)
            gold -= cost
            leveling += cost
            bought_xp += cost // rules.buy_xp_gold * rules.buy_xp
        if plan.level_above is not None and gold > plan.level_above:
            level, xp = level_after(start, natural_xp + augment_xp + bought_xp, rules)
            room = xp_cost(xp_missing(level, xp, top, rules), rules)
            cost = min((gold - plan.level_above) // rules.buy_xp_gold * rules.buy_xp_gold, room)
            gold -= cost
            leveling += cost
            bought_xp += cost // rules.buy_xp_gold * rules.buy_xp

        kind = round_kind(rnd)
        series.append(
            {
                "round": name_round(rnd),
                "kind": kind,
                "gold": gold,
                "natural_xp": natural_xp,
                "augment_xp": augment_xp,
                "bought_xp": bought_xp,
                "free_rolls": free_rolls,
                "spent": max(-entry, 0),
                "gained": max(entry, 0),
                "leveling": leveling,
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
            "level": level_after(start, earned_xp(point), rules)[0],
        }
        for point in series
    ]
    last = series[-1]
    level, xp = level_after(start, earned_xp(last), rules)
    levels = {}
    for target in LEVEL_TARGETS:
        missing = xp_missing(level, xp, target, rules)
        cost = xp_cost(missing, rules)
        levels[str(target)] = {
            "xp_missing": missing,
            "gold_cost": cost,
            "leftover": leftover(last["gold"], cost, last["free_roll_gold"]),
        }
    spent = sum(point["spent"] for point in series)
    leveling = sum(point["leveling"] for point in series)
    return {
        "gold": last["gold"],
        "free_roll_gold": last["free_roll_gold"],
        "total_gold": last["total_gold"],
        "natural_xp": last["natural_xp"],
        "augment_xp": last["augment_xp"],
        "bought_xp": last["bought_xp"],
        "free_rolls": last["free_rolls"],
        "spent": spent,
        "gained": sum(point["gained"] for point in series),
        "leveling": leveling,
        "ceiling": spent + leveling == 0,
        "level": level,
        "levels": levels,
        "series": series,
    }


def earned_xp(point: dict) -> int:
    """All the XP a series point has: natural, from augments and bought."""
    return point["natural_xp"] + point["augment_xp"] + point["bought_xp"]


def leftover(gold: int, cost: int, free_roll_gold: int) -> int:
    """What is left to roll with after buying a level: the gold left plus the Free Rolls, at
    what a roll costs. Free Rolls can't buy XP, so a shortfall is in gold alone (negative)."""
    return gold - cost + free_roll_gold if gold >= cost else gold - cost


def level_curve(scenario: dict, start: Start, rules: Rules) -> list[dict]:
    """Every level from the start's to the last target: `xp` to reach it from the level below,
    `total_xp` from the start, `reached_at` (the round the XP, bought included, reaches it, or
    None), and the `xp_missing` at the end round with the `gold_cost` that buys it."""
    last = scenario["series"][-1]
    level, xp = level_after(start, earned_xp(last), rules)
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
