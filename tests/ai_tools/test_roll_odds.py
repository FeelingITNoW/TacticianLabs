"""Tests for the roll odds calculator (include/ai_tools/roll_odds.py).

No fixtures are used, so `pytest --noconftest tests/ai_tools` runs on the host without Airflow.
"""

import pytest

from ai_tools import roll_odds
from ai_tools.roll_odds import RollTarget, calculate_roll_odds


def odds(*args, **kwargs):
    """The odds at the amounts of gold asked for."""
    return calculate_roll_odds(*args, **kwargs)["results"]


SAMPLE = [RollTarget("Lillia", 4, 3), RollTarget("Ahri", 4, 2), RollTarget("Rakan", 1, 1)]


def test_every_level_has_odds_that_add_up_to_one():
    for level, odds in roll_odds.SHOP_ODDS_PER_LEVEL.items():
        assert sum(odds.values()) == pytest.approx(1), level


def test_one_copy_is_the_chance_of_seeing_it_in_any_slot():
    # 4-cost at level 8 is 30% of slots, 10 of the 140 copies; the 4 gold buys the copy
    [result] = odds(8, [RollTarget("Ahri", 4, 1)], [54])

    p = 0.30 * 10 / 140
    assert result["rolls"] == 25
    assert result["all_units"] == pytest.approx(1 - (1 - p) ** (5 * 25), abs=1e-4)
    assert result["per_unit"] == {"Ahri": result["all_units"]}


def test_a_bought_copy_leaves_the_pool_of_its_cost():
    targets = [RollTarget("Ahri", 4, 1), RollTarget("Lillia", 4, 1)]
    shape = (2, 2)

    hits, stay = roll_odds.slot_odds(8, targets, {}, shape)

    # Nothing bought: 10 of 140. Ahri bought: Lillia is 10 of 139 and Ahri can't be bought again
    assert hits[1][0, 0] == pytest.approx(0.30 * 10 / 140)
    assert hits[1][1, 0] == pytest.approx(0.30 * 10 / 139)
    assert hits[0][1, 0] == 0
    assert stay[0, 0] == pytest.approx(1 - 2 * 0.30 * 10 / 140)


def test_copies_gone_shrink_the_unit_and_its_cost():
    targets = [RollTarget("Ahri", 4, 1, copies_out=3)]

    hits, _ = roll_odds.slot_odds(8, targets, {4: 40}, (2,))

    assert hits[0][0] == pytest.approx(0.30 * 7 / (140 - 40 - 3))


def test_the_sample_board_at_each_amount_of_gold():
    results = odds(8, SAMPLE)

    assert [r["gold"] for r in results] == [50, 60, 70, 80, 90, 100]
    assert [r["rolls"] for r in results] == [14, 19, 24, 29, 34, 39]
    assert results[0]["all_units"] == pytest.approx(0.033, abs=5e-4)
    assert results[2]["all_units"] == pytest.approx(0.210, abs=5e-4)
    assert results[5]["all_units"] == pytest.approx(0.586, abs=5e-4)
    # The board is only as likely as its hardest unit
    for result in results:
        assert result["all_units"] <= min(result["per_unit"].values())


def test_contested_pools_are_less_likely():
    open_pool = odds(8, SAMPLE, [100])[0]["all_units"]
    contested = [
        RollTarget("Lillia", 4, 3, copies_out=3),
        RollTarget("Ahri", 4, 2, copies_out=3),
        RollTarget("Rakan", 1, 1),
    ]

    assert odds(8, contested, [100])[0]["all_units"] < open_pool


def test_results_follow_the_order_of_the_gold_asked_for():
    results = odds(8, SAMPLE, [100, 50, 100])

    assert [r["gold"] for r in results] == [100, 50, 100]
    assert results[0] == results[2]
    assert results[0]["all_units"] > results[1]["all_units"]


def test_gold_that_cannot_buy_the_copies_is_zero_odds():
    [result] = odds(8, SAMPLE, [20])

    assert result["rolls"] == 0 and result["all_units"] == 0


def test_a_cost_the_level_never_shows_is_zero_odds():
    [result] = odds(3, [RollTarget("Ahri", 4, 1)], [300])

    assert result["all_units"] == 0


@pytest.mark.parametrize(
    "args",
    [
        dict(level=1, targets=SAMPLE),
        dict(level=12, targets=SAMPLE),
        dict(level=8, targets=[]),
        dict(level=8, targets=[RollTarget("Ahri", 4, 1), RollTarget("Ahri", 4, 1)]),
        dict(level=8, targets=[RollTarget("Ahri", 6, 1)]),
        dict(level=8, targets=[RollTarget("Ahri", 4, 0)]),
        dict(level=8, targets=[RollTarget("Ahri", 4, 1, copies_out=11)]),
        dict(level=8, targets=SAMPLE, tier_out={4: 141}),
        dict(level=8, targets=SAMPLE, tier_out={6: 1}),
        dict(level=8, targets=SAMPLE, gold=[]),
        dict(level=8, targets=SAMPLE, gold=[301]),
        dict(level=8, targets=SAMPLE, gold=[-1]),
        dict(level=8, targets=[RollTarget(f"u{i}", 1, 3) for i in range(9)]),
    ],
)
def test_input_with_no_answer_is_refused(args):
    with pytest.raises(ValueError):
        calculate_roll_odds(**args)


def test_the_curve_starts_when_the_copies_are_paid_for_and_steps_by_a_roll():
    curve = calculate_roll_odds(8, SAMPLE)["curve"]

    assert curve[0]["gold"] == 21 and curve[0]["rolls"] == 0 and curve[0]["all_units"] == 0
    assert [p["gold"] for p in curve[:3]] == [21, 23, 25]
    assert [p["rolls"] for p in curve] == list(range(len(curve)))
    assert all(a["all_units"] <= b["all_units"] for a, b in zip(curve, curve[1:]))


def test_the_curve_stops_at_the_first_point_at_95_percent():
    curve = calculate_roll_odds(8, SAMPLE)["curve"]

    assert curve[-1]["all_units"] >= roll_odds.CURVE_TARGET > curve[-2]["all_units"]
    assert curve[-1]["gold"] == 167


def test_an_easy_board_still_covers_100_gold():
    curve = calculate_roll_odds(8, [RollTarget("Rakan", 1, 1)], [50])["curve"]

    assert curve[0]["gold"] == 1
    assert curve[-1]["gold"] >= roll_odds.CURVE_MIN_GOLD
    assert curve[-1]["all_units"] > roll_odds.CURVE_TARGET


def test_a_hard_board_stops_at_the_gold_cap():
    curve = calculate_roll_odds(8, [RollTarget("Sivir", 4, 9)])["curve"]

    assert curve[-1]["gold"] <= roll_odds.MAX_GOLD
    assert curve[-1]["gold"] >= roll_odds.MAX_GOLD - roll_odds.ROLL_COST
    assert curve[-1]["all_units"] < roll_odds.CURVE_TARGET


def test_an_amount_asked_for_past_95_percent_extends_the_curve():
    short = calculate_roll_odds(8, SAMPLE, [100])["curve"]
    asked = calculate_roll_odds(8, SAMPLE, [250])["curve"]

    assert short[-1]["gold"] == 167
    assert asked[-1]["gold"] >= 249 and asked[-1]["all_units"] > short[-1]["all_units"]


def test_a_result_is_the_curve_point_with_the_same_rolls():
    out = calculate_roll_odds(8, SAMPLE, [57, 100, 10])

    for row in out["results"]:
        point = out["curve"][row["rolls"]]
        assert row["all_units"] == point["all_units"] and row["per_unit"] == point["per_unit"]
    # Gold that can't buy the copies sits at the start of the curve
    assert out["results"][2]["rolls"] == 0 and out["results"][2]["all_units"] == 0
