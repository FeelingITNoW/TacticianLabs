"""Tests for the gold and XP projection (include/ai_tools/gold_projection.py).

No fixtures are used, so `pytest --noconftest tests/ai_tools` runs on the host without Airflow.
Every test passes its own Rules, so the placeholder numbers in the module don't matter here.
"""

import pytest

from ai_tools import gold_projection
from ai_tools.gold_projection import (
    Augment,
    AugmentPick,
    Rules,
    ScenarioPlan,
    Start,
    calculate_gold_projection,
    parse_round,
)

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
    """The three presets, by name"""
    scenarios = calculate_gold_projection(end, augments, start, RULES, **kwargs)["scenarios"]
    return {s["preset"]: s for s in scenarios}


def plan(fights="win", gold=None, levels=None, level_above=None, label=None):
    return ScenarioPlan(
        fights,
        label,
        {parse_round(k): v for k, v in (gold or {}).items()},
        {parse_round(k): v for k, v in (levels or {}).items()},
        level_above,
    )


def custom(*plans, end=None, augments=None, start=START, **kwargs):
    """The scenarios of a call with custom plans, in order"""
    result = calculate_gold_projection(
        end, augments, start, RULES, scenarios=list(plans), **kwargs
    )
    return result["scenarios"]


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
    scenarios = calculate_gold_projection(end, augments, start, RULES)["scenarios"]
    return scenarios[0]["level_curve"]


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
    scenario = calculate_gold_projection("4-2", None, Start(), RULES)["scenarios"][0]
    rows = {row["level"]: row for row in scenario["level_curve"]}
    for target in ("8", "9"):
        level = scenario["levels"][target]
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


# --- custom fights, spending and levelling ---


def end_of(*plans, end=None, start=START):
    return calculate_gold_projection(end, None, start, RULES, scenarios=list(plans))["end_round"]


def test_a_fight_string_sets_the_end_round_to_the_round_after_its_last_fight():
    # 2-1 to 4-1 is 11 PvP fights, 4-2 the 12th... 15 fights end at 4-7
    assert end_of(plan("w" * 15)) == "4-7"
    assert end_of(plan("wlw")) == "2-4"
    assert end_of(plan("w" * 11)) == "4-2"
    assert end_of(plan("w")) == "2-2"


def test_a_fight_string_is_one_letter_per_pvp_fight_and_matches_the_presets():
    assert custom(plan("w" * 11), end="4-2")[0]["gold"] == project("4-2")["win"]["gold"]
    assert custom(plan("l" * 11), end="4-2")[0]["gold"] == project("4-2")["loss"]["gold"]


def test_a_mixed_fight_string_follows_the_streak_through_a_win_then_a_loss():
    # 2-1: 4. A win (streak 1, pays 1) -> 2-2: 4 + 5 + 1 = 10. A loss breaks the streak and pays 0
    # -> 2-3: 10 + 1 interest + 5 = 16. A win pays 1, a streak of 1 pays 0 -> 2-4: 16 + 1 + 5 + 1
    scenario = custom(plan("wlw"))[0]
    assert golds(scenario) == [4, 10, 16, 23]
    assert scenario["fights"] == "wlw" and scenario["preset"] is None


def test_a_fight_string_ignores_case_and_spaces():
    assert custom(plan("WW l"))[0]["gold"] == custom(plan("wwl"))[0]["gold"]


@pytest.mark.parametrize(
    "fights, end, message",
    [
        ("www", "4-2", "has 3 letters but 2-1 to 4-2 has 11 PvP fights"),
        ("w" * 12, "4-2", "2-1, 2-2, 2-3, 2-5, 2-6, 3-1"),
        ("wxl", None, "string of w and l"),
        ("", None, "string of w and l"),
        ("w" * 40, None, "at most"),
    ],
)
def test_a_fight_string_that_does_not_fit_is_refused_with_the_rounds_it_expected(
    fights, end, message
):
    with pytest.raises(ValueError, match=message):
        custom(plan(fights), end=end)


def test_fight_strings_that_end_at_different_rounds_are_refused():
    with pytest.raises(ValueError, match="different rounds"):
        custom(plan("www"), plan("wwww"))


def test_presets_and_strings_can_share_a_call():
    result = custom(plan("mixed"), plan("wlw"))
    assert [s["preset"] for s in result] == ["mixed", None]
    assert result[0]["series"][-1]["round"] == "2-4"


def test_labels_default_to_the_preset_name_or_a_number_and_can_be_set():
    result = custom(plan("win"), plan("wlw"), plan("loss", label="Save it"), end="2-4")
    assert [s["label"] for s in result] == ["Win streak", "Custom 2", "Save it"]


def test_a_call_runs_at_most_three_scenarios():
    with pytest.raises(ValueError, match="at most 3"):
        custom(*[plan("win")] * 4, end="2-4")


def test_gold_entries_spend_and_gain_in_their_round():
    start = START
    scenario = custom(plan("w" * 4, gold={"2-1": -3, "2-2": 12}), end="2-6", start=start)[0]
    # 2-1: 4 - 3 = 1. 2-2: 1 + 0 interest + 5 + 1 (win) = 7, then +12 = 19
    assert golds(scenario)[:2] == [1, 19]
    assert [p["spent"] for p in scenario["series"]][:2] == [3, 0]
    assert [p["gained"] for p in scenario["series"]][:2] == [0, 12]
    assert scenario["spent"] == 3 and scenario["gained"] == 12 and scenario["ceiling"] is False


def test_interest_is_paid_on_what_is_left_after_spending():
    rich = Start(round=(2, 1), level=4, xp=0, gold=100)
    # 2-1: 100 + 5 interest + 4 = 109, spend 80 -> 29. 2-2: 29 + 2 interest + 5 + 1 (win)
    scenario = custom(plan("w", gold={"2-1": -80}), start=rich)[0]
    assert golds(scenario) == [29, 37]


def test_the_presets_spend_nothing_and_are_a_ceiling():
    assert all(s["ceiling"] for s in project().values())
    assert all(s["spent"] == 0 and s["leveling"] == 0 for s in project().values())


def test_a_level_target_buys_the_xp_still_missing_in_whole_purchases():
    rich = Start(round=(2, 1), level=4, xp=0, gold=20)
    scenario = custom(plan("w", levels={"2-1": 5}), start=rich)[0]
    # 2-1: 20 + 2 interest + 4 = 26. Natural XP 2 puts it at level 4 with 2: 8 XP to level 5 is 8 gold
    first = scenario["series"][0]
    assert first["gold"] == 18 and first["leveling"] == 8
    assert first["bought_xp"] == 8 and first["level"] == 5
    assert scenario["ceiling"] is False


def test_a_level_target_rounds_up_to_a_whole_purchase_and_keeps_the_spare_xp():
    rich = Start(round=(2, 1), level=4, xp=1, gold=20)
    first = custom(plan("w", levels={"2-1": 5}), start=rich)[0]["series"][0]
    # 1 + 2 natural = 3 of 10: 7 missing is two purchases, 8 XP, which leaves 1 XP in level 5
    assert first["leveling"] == 8 and first["bought_xp"] == 8
    assert first["level"] == 5


def test_a_level_already_reached_costs_nothing_and_a_missing_level_is_refused():
    rich = Start(round=(2, 1), level=4, xp=0, gold=20)
    first = custom(plan("w", levels={"2-1": 4}), start=rich)[0]["series"][0]
    assert first["leveling"] == 0 and first["bought_xp"] == 0
    for target in (1, 11):
        with pytest.raises(ValueError, match="from 2 to 10"):
            custom(plan("w", levels={"2-1": target}), start=rich)


def test_level_above_buys_xp_with_every_whole_four_gold_over_the_line():
    rich = Start(round=(2, 1), level=4, xp=0, gold=100)
    first = custom(plan("w", level_above=50), start=rich)[0]["series"][0]
    # 2-1: 109, 59 over the line is 14 purchases: 56 gold, 56 XP; 2 natural + 56 is level 6, 28 in
    assert first["gold"] == 53 and first["leveling"] == 56 and first["bought_xp"] == 56
    assert first["level"] == 6


def test_level_above_stops_at_the_top_of_the_xp_table():
    top = Start(round=(2, 1), level=9, xp=80, gold=300)
    scenario = custom(plan("w", level_above=0), start=top)[0]
    first, second = scenario["series"]
    # 2 natural XP leaves 2 of 84: one purchase is enough, and level 10 takes no more
    assert first["leveling"] == 4 and first["level"] == 10
    assert second["leveling"] == 0 and scenario["bought_xp"] == 4


def test_a_round_gains_gold_then_levels_to_its_target_then_buys_above_the_line():
    rich = Start(round=(2, 1), level=4, xp=0, gold=0)
    first = custom(
        plan("w", gold={"2-1": 20}, levels={"2-1": 5}, level_above=10), start=rich
    )[0]["series"][0]
    # 4 + 20 = 24, level 5 costs 8 -> 16, then one purchase over the line of 10 -> 12
    assert first["gold"] == 12 and first["leveling"] == 12 and first["bought_xp"] == 12


def test_the_end_rounds_own_moves_count_before_the_levels_are_priced():
    rich = Start(round=(2, 1), level=4, xp=0, gold=20)
    scenario = custom(plan("w", levels={"2-2": 5}), end="2-2", start=rich)[0]
    # 2-2 holds 34, buys level 5 for 8; 4 natural + 8 bought is level 5 with 2 in
    assert scenario["gold"] == 26 and scenario["level"] == 5
    assert scenario["levels"]["8"]["xp_missing"] == (20 - 2) + 36 + 48
    assert scenario["levels"]["8"]["gold_cost"] == 104
    assert scenario["levels"]["8"]["leftover"] == 26 - 104


def test_levelling_moves_the_level_curve_of_its_scenario_only():
    rich = Start(round=(2, 1), level=4, xp=0, gold=20)
    bought, saved = custom(plan("win", levels={"2-1": 5}), plan("loss"), end="2-3", start=rich)
    rows = {row["level"]: row for row in bought["level_curve"]}
    assert rows[5]["reached_at"] == "2-1" and rows[5]["xp_missing"] == 0
    assert {r["level"]: r for r in saved["level_curve"]}[5]["reached_at"] is None


def test_a_move_outside_the_projection_is_refused():
    with pytest.raises(ValueError, match="projection runs 2-1 to 4-2"):
        custom(plan("w" * 11, gold={"4-3": -1}), end="4-2")
    with pytest.raises(ValueError, match="levels has round"):
        custom(plan("w", levels={"3-1": 5}), end="2-2")


def test_spending_more_than_is_held_is_refused_with_the_balances_so_far():
    with pytest.raises(ValueError) as error:
        custom(plan("w" * 4, gold={"2-3": -50}), end="2-6")
    message = str(error.value)
    assert "Custom 1: spending 50 gold at 2-3 needs 50 gold but only 18 is held" in message
    assert "2-1 4, 2-2 10" in message


def test_a_level_target_that_cannot_be_paid_is_refused():
    with pytest.raises(ValueError, match="reaching level 9 at 2-1 needs"):
        custom(plan("w", levels={"2-1": 9}), end="2-2")


def test_the_first_round_has_no_balances_to_show():
    with pytest.raises(ValueError, match="none yet"):
        custom(plan("w", gold={"2-1": -50}), end="2-2")


def test_a_mixed_plan_must_be_affordable_in_every_run():
    # 2-2 holds 10 after a win and 9 after a loss
    ok = custom(plan("mixed", gold={"2-2": -9}), end="2-6")[0]
    assert ok["series"][1]["spent"] == 9
    with pytest.raises(ValueError, match="lowest of the 400 random runs") as error:
        custom(plan("mixed", gold={"2-2": -10}), end="2-6")
    assert "only 9 is held" in str(error.value)


def test_level_above_never_overspends_in_a_mixed_plan_and_follows_the_gold():
    win, mixed_run, loss = custom(
        plan("win", level_above=0), plan("mixed", level_above=0), plan("loss", level_above=0),
        end="4-2",
    )
    # the same order as their gold: the mixed scenario never builds a streak
    assert win["bought_xp"] > loss["bought_xp"] > mixed_run["bought_xp"] > 0
    assert all(p["gold"] >= 0 for s in (win, mixed_run, loss) for p in s["series"])


def test_a_custom_call_is_the_same_every_time():
    plans = [plan("mixed", gold={"2-2": -9}, levels={"3-2": 5}, level_above=20)]
    start = Start(round=(2, 1), level=4, xp=0, gold=30)
    assert custom(*plans, end="4-2", start=start) == custom(*plans, end="4-2", start=start)
