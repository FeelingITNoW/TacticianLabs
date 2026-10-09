"""Tests for the rebuild_stats command (include/jobs/rebuild_stats.py)."""

from datetime import datetime, timezone

import pytest

from jobs import rebuild_stats

WINDOW = {
    "lo": datetime(2026, 9, 24, tzinfo=timezone.utc),
    "hi": datetime(2026, 10, 8, tzinfo=timezone.utc),
}


@pytest.fixture(autouse=True)
def use_fake_bq(fake_bq, monkeypatch):
    monkeypatch.setattr(rebuild_stats, "make_client", lambda: fake_bq)


def test_latest_resolves_the_newest_patch(fake_bq, capsys):
    fake_bq.query_rows = [{"patch": "16.19.1", **WINDOW}]

    code = rebuild_stats.main(
        ["--table", "champion_item_pair_totals", "--patch", "latest"]
    )

    assert code == 0
    assert (
        "Rebuilt champion_item_pair_totals for patch 16.19.1" in capsys.readouterr().out
    )
    _, params = fake_bq.queries[-1]
    assert params[0].value == "16.19.1"


def test_an_unknown_table_is_rejected():
    with pytest.raises(SystemExit):
        rebuild_stats.main(["--table", "nope"])


def test_a_patch_with_no_ranked_matches_exits_1(fake_bq, capsys):
    fake_bq.query_rows = [{"lo": None, "hi": None}]

    code = rebuild_stats.main(["--patch", "16.1.1"])

    assert code == 1
    assert "No ranked matches for patch 16.1.1" in capsys.readouterr().out
    assert len(fake_bq.queries) == 1


def test_check_reports_mismatches(fake_bq, capsys):
    fake_bq.query_rows = [{"mismatches": 3, **WINDOW}]

    code = rebuild_stats.main(
        ["--check", "--table", "item_totals", "--patch", "16.19.1"]
    )

    assert code == 1
    assert "item_totals: 3 mismatched rows" in capsys.readouterr().out
