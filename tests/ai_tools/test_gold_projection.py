"""Tests for the gold and XP projection (include/ai_tools/gold_projection.py).

No fixtures are used, so `pytest --noconftest tests/ai_tools` runs on the host without Airflow.
Every test passes its own Rules, so the placeholder numbers in the module don't matter here.
"""

import pytest

from ai_tools import gold_projection
from ai_tools.gold_projection import Augment, AugmentPick, Rules, Start, calculate_gold_projection

RULES = Rules(
    passive_first=4,
    passive=5,
    neutral_gold=6,
    carousel_gold=3,
    win_gold=1,
    streak_tiers=((2, 1), (4, 2), (5, 3)),
    interest_per=10,
    interest_cap=5,
    natural_xp=2,
    xp_to_level_up={1: 2, 2: 2, 3: 6, 4: 10, 5: 20, 6: 36, 7: 48, 8: 76, 9: 84},
    buy_xp=4,
    buy_xp_gold=4,
)
START = Start(round=(2, 1), level=4, xp=0, gold=0)


def project(end="4-2", augments=None, start=START, **kwargs):
    return calculate_gold_projection(end, augments, start, RULES, **kwargs)["scenarios"]


def golds(scenario):
    return [point["gold"] for point in scenario["series"]]


def pick(slot, **effects):
    return AugmentPick(Augment("Test", **effects), slot)


def test_a_win_streak_pays_passive_win_and_streak_gold_with_interest():
    # 2-1: 4. A win pays 1 (streak 1 pays 0): 2-2 is 4 + 5 + 1. A second win pays 1 + 1:
    # 2-3 is 10 + 1 interest + 5 + 2
    assert golds(project("2-3")["win"]) == [4, 10, 18]


def test_a_loss_streak_pays_streak_gold_and_no_win_gold():
    # 2-1: 4. 2-2: 4 + 5 (a first loss pays nothing). A second loss pays 1: 2-3 is 9 + 5 + 1
    assert golds(project("2-3")["loss"]) == [4, 9, 15]


def test_carousels_and_neutrals_pay_a_round_late_and_keep_the_streak():
    win = golds(project("3-1")["win"])
    # 2-4 is a carousel, which pays 3 at 2-5; 2-7 is neutrals, which pay 6 at 3-1
    deltas = [b - a for a, b in zip(win, win[1:])]
    rounds = [point["round"] for point in project("3-1")["win"]["series"]]
    assert rounds == ["2-1", "2-2", "2-3", "2-4", "2-5", "2-6", "2-7", "3-1"]
    assert deltas[3] == 5 + 4 + 1  # 2-4: interest on 28 is 2, +5 passive +the win/streak of 2-3
    assert deltas[6] >= 5 + 6  # 3-1 pays the neutrals' 6 on top of passive
    # a win at 2-5 is the 4th win in a row: the carousel and nothing else did not break it
    assert project("2-6")["win"]["series"][5]["gold"] - win[4] == (
        win[4] // 10 + 5 + 1 + 2  # interest, passive, win gold, streak of 4
    )


def test_the_end_rounds_own_fight_is_not_counted():
    # 2-2 reports the planning phase: the 2-2 fight has not been fought
    assert project("2-2")["win"]["gold"] == 10
    assert project("2-2")["loss"]["gold"] == 9


def test_interest_is_capped_and_an_augment_raises_the_cap():
    rich = Start(gold=100)
    capped = project("2-2", start=rich)["loss"]["gold"]
    assert capped == 100 + 5 + 4 + 5 + 5  # interest 5 and passive 4 at 2-1, interest 5 and passive 5 at 2-2
    raised = project("2-2", [pick((2, 1), max_interest=2)], start=rich)["loss"]["gold"]
    assert raised == capped + 2 * 2  # two planning phases at the higher cap


def test_free_rolls_count_in_the_gold_at_what_a_roll_costs():
    scenario = project("3-2", [pick((2, 1), free_rolls=3)])["win"]
    assert scenario["free_roll_gold"] == 3 * 2
    assert scenario["total_gold"] == scenario["gold"] + 6
    assert scenario["gold"] == project("3-2")["win"]["gold"]  # they earn no interest
    first = scenario["series"][0]
    assert first["free_roll_gold"] == 6 and first["total_gold"] == first["gold"] + 6


def test_free_rolls_are_left_over_to_roll_with_after_a_level():
    scenario = project("4-2", [pick((2, 1), free_rolls=3)])["win"]
    level_8 = scenario["levels"]["8"]
    assert level_8["leftover"] == scenario["gold"] - level_8["gold_cost"] + 6


def test_free_rolls_cannot_cover_a_shortfall_of_gold():
    scenario = project("2-2", [pick((2, 1), free_rolls=50)])["loss"]
    level_9 = scenario["levels"]["9"]
    assert level_9["leftover"] == scenario["gold"] - level_9["gold_cost"] < 0


def test_augment_gold_and_free_rolls_arrive_once_at_the_slot():
    scenario = project("3-2", [pick((2, 1), gold=10, free_rolls=2)])["loss"]
    plain = project("3-2")["loss"]
    assert scenario["free_rolls"] == 2
    assert scenario["series"][0]["free_rolls"] == 2
    assert scenario["series"][0]["gold"] == plain["series"][0]["gold"] + 10
    assert scenario["gold"] > plain["gold"] + 10  # the 10 gold also earned interest


def test_augment_xp_counts_per_round_from_its_slot_and_apart_from_natural_xp():
    scenario = project("4-2", [pick((3, 2), xp_per_round=4)])["win"]
    # 3-2 to 3-7, then 4-1 and 4-2: 8 rounds
    assert scenario["augment_xp"] == 4 * 8
    assert scenario["natural_xp"] == 2 * 16
    assert project("4-2")["win"]["augment_xp"] == 0


def test_an_augment_after_the_end_round_is_refused():
    with pytest.raises(ValueError, match="after the end round"):
        project("3-1", [pick((3, 2), gold=5)])


def test_a_slot_before_the_start_still_gives_its_per_round_effects():
    late = Start(round=(3, 2), level=6, xp=0, gold=20)
    scenario = project("3-3", [pick((2, 1), gold=99, xp_per_round=3)], start=late)["win"]
    assert scenario["augment_xp"] == 3 * 2  # 3-2 and 3-3
    assert scenario["series"][0]["gold"] == project("3-3", start=late)["win"]["series"][0]["gold"]


def test_level_costs_are_whole_four_gold_purchases_with_a_shortfall_negative():
    scenario = project("4-2")["loss"]
    # 32 XP from 2 per round over 16 rounds: level 4 -> 6 (10 + 20 needed, 30), 2 into level 6
    assert scenario["level"] == 6 and scenario["natural_xp"] == 32
    level_8 = scenario["levels"]["8"]
    assert level_8["xp_missing"] == (36 + 48) - 2
    assert level_8["gold_cost"] == 21 * 4  # 82 XP is 21 buys of 4
    assert level_8["leftover"] == scenario["gold"] - 84
    level_9 = scenario["levels"]["9"]
    assert level_9["xp_missing"] == 82 + 76
    assert level_9["gold_cost"] == 40 * 4  # 158 XP is 40 buys (160 XP)
    assert level_9["leftover"] == scenario["gold"] - 160


def test_a_level_already_reached_costs_nothing():
    high = Start(level=8, xp=10, gold=30)
    levels = project("2-2", start=high)["win"]["levels"]
    assert levels["8"] == {"xp_missing": 0, "gold_cost": 0, "leftover": project("2-2", start=high)["win"]["gold"]}
    assert levels["9"]["xp_missing"] == 76 - 10 - 2 * 2


def test_xp_does_not_depend_on_the_streak_scenario():
    scenarios = project("4-2")
    assert len({s["natural_xp"] for s in scenarios.values()}) == 1
    assert len({s["level"] for s in scenarios.values()}) == 1


def test_the_mixed_scenario_is_the_same_every_time():
    assert project("4-2")["mixed"] == project("4-2")["mixed"]


def test_the_mixed_scenario_earns_least_because_it_never_builds_a_streak():
    scenarios = project("4-2")
    assert scenarios["mixed"]["gold"] < scenarios["loss"]["gold"] < scenarios["win"]["gold"]


def test_a_stage_with_fewer_pvp_rounds_than_its_wins_has_them_all_won():
    # 4-1 is the only PvP round of stage 4 before 4-2: always a win, so mixed pays its win gold
    start = Start(round=(4, 1), level=7, xp=0, gold=0)
    scenarios = project("4-2", start=start)
    assert scenarios["mixed"]["gold"] == scenarios["win"]["gold"]


def test_a_streak_already_running_carries_on_for_a_win_and_breaks_for_a_loss():
    start = Start(round=(3, 1), level=6, xp=0, gold=0, streak=3)
    base = project("3-3", start=Start(round=(3, 1), level=6, xp=0, gold=0))
    running = project("3-3", start=start)
    # a 3-win streak: a fourth win pays win gold + the streak's 2 gold, instead of 1 + 0
    assert running["win"]["gold"] == base["win"]["gold"] + 2 + 1 + 1
    # a loss breaks it, so a first loss pays nothing, the same as with no streak
    assert running["loss"]["series"][1]["gold"] == base["loss"]["series"][1]["gold"]


def test_a_running_loss_streak_pays_when_the_loss_scenario_continues_it():
    start = Start(round=(3, 1), level=6, xp=0, gold=0, streak=-1)
    base = project("3-3", start=Start(round=(3, 1), level=6, xp=0, gold=0))
    assert project("3-3", start=start)["loss"]["series"][1]["gold"] == (
        base["loss"]["series"][1]["gold"] + 1
    )


def test_the_series_has_a_point_per_round_from_the_start_to_the_end():
    series = project("3-2")["win"]["series"]
    assert [p["round"] for p in series][0] == "2-1" and series[-1]["round"] == "3-2"
    assert len(series) == 9


def test_the_second_stage_start_uses_the_later_passive_income():
    start = Start(round=(3, 1), level=6, xp=0, gold=0)
    assert project("3-2", start=start)["loss"]["series"][0]["gold"] == RULES.passive


@pytest.mark.parametrize(
    "args",
    [
        dict(end_round="2-1"),
        dict(end_round="5-3"),
        dict(end_round="6-1"),
        dict(end_round="4-8"),
        dict(end_round="soon"),
        dict(end_round="4-2", start=Start(round=(4, 2))),
        dict(end_round="4-2", start=Start(round=(1, 4))),
        dict(end_round="4-2", start=Start(level=12)),
        dict(end_round="4-2", start=Start(level=4, xp=10)),
        dict(end_round="4-2", start=Start(gold=-1)),
        dict(end_round="4-2", start=Start(gold=501)),
        dict(end_round="4-2", augments=[pick((2, 1)), pick((2, 1))]),
        dict(end_round="4-2", augments=[pick((3, 3))]),
    ],
)
def test_input_with_no_answer_is_refused(args):
    kwargs = {"end_round": "4-2", "augments": None, "start": START, **args}
    with pytest.raises(ValueError):
        calculate_gold_projection(rules=RULES, **kwargs)


def test_the_default_end_round_is_4_2():
    assert gold_projection.calculate_gold_projection()["end_round"] == "4-2"


def test_the_masterlist_ships_empty_until_real_values_are_supplied(tmp_path):
    assert gold_projection.load_augments() == {}
    path = tmp_path / "augments.json"
    path.write_text('[{"name": "Pot of Gold", "gold": 8, "max_interest": 1}]')
    assert gold_projection.load_augments(path) == {
        "Pot of Gold": Augment("Pot of Gold", gold=8, max_interest=1)
    }


def test_a_target_the_gold_cannot_buy_shows_a_negative_leftover():
    early = project("2-2")["loss"]
    assert early["levels"]["9"]["leftover"] == early["gold"] - early["levels"]["9"]["gold_cost"]
    assert early["levels"]["9"]["leftover"] < 0


def curve(end="4-2", augments=None, start=None):
    start = start or Start(round=(2, 1), level=3, xp=0, gold=0)
    return calculate_gold_projection(end, augments, start, RULES)["level_curve"]


def test_a_player_arrives_at_2_1_on_level_3_by_default():
    assert Start().level == 3
    assert gold_projection.calculate_gold_projection()["start"]["level"] == 3


def test_the_level_curve_runs_from_level_3_to_level_9():
    rows = curve()
    assert [row["level"] for row in rows] == [4, 5, 6, 7, 8, 9]
    assert [row["xp"] for row in rows] == [6, 10, 20, 36, 48, 76]
    assert [row["total_xp"] for row in rows] == [6, 16, 36, 72, 120, 196]


def test_the_level_curve_says_when_the_xp_alone_reaches_a_level():
    rows = {row["level"]: row for row in curve()}
    # 2 XP a round: 6 XP is the 3rd round (2-3), 16 the 8th (3-1), 36 the 18th, after 4-2
    assert rows[4]["reached_at"] == "2-3"
    assert rows[5]["reached_at"] == "3-1"
    assert rows[6]["reached_at"] is None


def test_the_level_curve_prices_what_is_missing_at_the_end_round():
    rows = {row["level"]: row for row in curve()}
    # 32 XP by 4-2: level 5 with 16 towards level 6
    assert rows[5]["xp_missing"] == 0 and rows[5]["gold_cost"] == 0
    assert rows[6]["xp_missing"] == 4 and rows[6]["gold_cost"] == 4
    assert rows[9]["xp_missing"] == 196 - 32
    assert rows[9]["gold_cost"] == 164


def test_the_level_curve_matches_the_scenarios_prices():
    result = calculate_gold_projection("4-2", None, Start(), RULES)
    rows = {row["level"]: row for row in result["level_curve"]}
    for target in ("8", "9"):
        level = result["scenarios"]["win"]["levels"][target]
        assert rows[int(target)]["gold_cost"] == level["gold_cost"]
        assert rows[int(target)]["xp_missing"] == level["xp_missing"]


def test_the_level_curve_starts_from_the_start_and_counts_its_xp():
    rows = curve(start=Start(round=(3, 2), level=6, xp=5, gold=0))
    assert [row["level"] for row in rows] == [7, 8, 9]
    assert rows[0]["total_xp"] == 36 - 5


def test_the_level_curve_is_empty_from_the_last_target():
    assert curve(start=Start(level=9)) == []


def test_augment_xp_moves_the_level_curve():
    rows = {r["level"]: r for r in curve(augments=[pick((2, 1), xp_per_round=4)])}
    # 6 XP a round: level 4 at 2-1, and 16 XP by 2-3
    assert rows[4]["reached_at"] == "2-1"
    assert rows[5]["reached_at"] == "2-3"


def test_every_round_says_its_kind_level_and_income():
    series = project("3-1", start=Start(round=(2, 1), level=3, xp=0, gold=0))["win"]["series"]
    assert [point["kind"] for point in series][:7] == [
        "pvp", "pvp", "pvp", "carousel", "pvp", "pvp", "neutral"
    ]
    assert [point["level"] for point in series][:3] == [3, 3, 4]
    assert series[2]["income"] == {"interest": 1, "passive": 5, "reward": 2, "augment": 0}
    # neutrals at 2-7 pay at 3-1
    assert series[7]["income"]["reward"] == 6


def test_income_adds_up_to_the_change_in_gold():
    series = project("4-2", [pick((3, 2), gold=10)])["win"]["series"]
    for before, after in zip(series, series[1:]):
        assert sum(after["income"].values()) == after["gold"] - before["gold"]


def test_the_mixed_income_is_the_average_of_its_runs():
    series = project("4-2")["mixed"]["series"]
    # the first fight's reward is averaged over runs that won and lost it
    assert 0 < series[1]["income"]["reward"] < 1
    for before, after in zip(series, series[1:]):
        assert abs(sum(after["income"].values()) - (after["gold"] - before["gold"])) <= 1
