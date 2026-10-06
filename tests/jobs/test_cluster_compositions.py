"""Tests for composition clustering (include/data_aggregation/compositions.py)."""

import random
from collections import Counter

import numpy as np
import pytest

from data_aggregation import compositions
from data_aggregation.compositions import (
    BOARDS_SQL,
    assign,
    build_boards,
    cluster_patch,
    fetch_boards,
    fit_clusters,
    summarize,
    write_compositions,
)

PATCH = "16.19.1"


def feature(name: str, items: int = 0, star: int = 2) -> dict:
    """A unit as the boards query returns it: value is 1 + items."""
    return {"feature": f"u:{name}", "value": 1 + items, "star": star}


def trait(name: str, tier: int) -> dict:
    return {"feature": f"t:{name}", "value": tier, "star": 0}


def row(index: int, features: list[dict], placement: int = 4, match: int | None = None) -> dict:
    return {
        "match_id": f"NA1_{index if match is None else match}",
        "puuid": f"puuid{index}",
        "played_at": "2026-09-28T12:00:00+00:00",
        "placement": placement,
        "features": features,
    }


def comp_rows(
    rng: random.Random,
    name: str,
    carry: int,
    count: int,
    start: int,
    units: list[str] | None = None,
) -> list[dict]:
    """Boards of one comp: its 8 units (the carry always on 3 items), one of the others
    sometimes swapped for a splash unit, and the same two traits."""
    units = units or [f"{name}{i}" for i in range(8)]
    rows = []
    for i in range(count):
        chosen = list(units)
        if rng.random() < 0.5:
            chosen[rng.choice([n for n in range(8) if n != carry])] = f"Splash{rng.randrange(20)}"
        features = [
            feature(unit, 3 if n == carry else rng.choice([0, 0, 1]))
            for n, unit in enumerate(chosen)
        ]
        features += [trait(f"{name}Trait", 2), trait("Shared", 1)]
        rows.append(row(start + i, features, placement=rng.randint(1, 8)))
    return rows


def noise_rows(rng: random.Random, count: int, start: int) -> list[dict]:
    pool = [f"Other{i}" for i in range(80)]
    return [
        row(
            start + i,
            [feature(unit, rng.choice([0, 1, 2])) for unit in rng.sample(pool, 8)]
            + [trait(f"Noise{rng.randrange(30)}", 2)],
        )
        for i in range(count)
    ]


def label_counts(labels: np.ndarray, start: int, count: int) -> Counter:
    return Counter(int(label) for label in labels[start : start + count])


class TestBuildBoards:
    def boards(self):
        return build_boards(
            [
                row(
                    0,
                    [
                        feature("Ahri", items=3, star=3),
                        feature("Nami"),
                        trait("Mage", 4),
                    ],
                ),
                row(1, [feature("Nami", items=1), trait("Mage", 2)]),
            ]
        )

    def test_columns_are_sorted_and_prefixed(self):
        assert self.boards().features == ["t:Mage", "u:Ahri", "u:Nami"]

    def test_a_unit_weighs_one_plus_its_items(self):
        raw = self.boards().raw.toarray()

        assert raw[0, 1] == 4  # Ahri, three items
        assert raw[0, 2] == 1  # Nami, none
        assert raw[1, 2] == 2  # Nami, one item
        assert raw[1, 1] == 0  # Ahri isn't on the second board

    def test_traits_carry_their_tier(self):
        assert self.boards().raw.toarray()[:, 0].tolist() == [4, 2]

    def test_rows_have_unit_length_and_the_carry_dominates(self):
        vectors = self.boards().vectors.toarray()

        assert np.linalg.norm(vectors, axis=1) == pytest.approx([1, 1])
        assert vectors[0, 1] == pytest.approx(4 * vectors[0, 2])

    def test_trait_weight_scales_trait_columns(self, monkeypatch):
        monkeypatch.setattr(compositions, "TRAIT_WEIGHT", 0.0)
        vectors = self.boards().vectors.toarray()

        assert vectors[:, 0].tolist() == [0, 0]

    def test_star_levels_are_kept_apart_from_the_vector(self):
        assert self.boards().stars.toarray()[0].tolist() == [0, 3, 2]

    def test_empty(self):
        assert len(build_boards([])) == 0


class TestBoardsSql:
    def test_unit_weight_counts_items_and_keeps_the_best_copy(self):
        assert "MAX(1 + COALESCE(i.items, 0))" in BOARDS_SQL

    def test_only_active_traits(self):
        assert "WHERE tier_current > 0" in BOARDS_SQL

    def test_filters_on_the_patch_parameter(self, fake_bq):
        fake_bq.query_rows = [row(0, [feature("Ahri"), trait("Mage", 2)])]

        boards = fetch_boards(fake_bq, PATCH)

        sql, params = fake_bq.queries[0]
        assert "test-project.tft.participant_units" in sql
        assert "m.game_version = @patch" in sql
        assert [(p.name, p.value) for p in params] == [("patch", PATCH)]
        assert len(boards) == 1


class TestClustering:
    def test_recovers_comps_and_leaves_off_meta_boards_out(self):
        rng = random.Random(1)
        rows = (
            comp_rows(rng, "A", 0, 120, 0)
            + comp_rows(rng, "B", 0, 120, 120)
            + comp_rows(rng, "C", 0, 120, 240)
            + noise_rows(rng, 60, 360)
        )
        boards = build_boards(rows)

        clusters = fit_clusters(boards.vectors, min_cluster_size=20)
        labels, similarity = assign(boards.vectors, clusters)

        modes = []
        for start in (0, 120, 240):
            (label, hits), *_ = label_counts(labels, start, 120).most_common(1)
            assert label >= 0
            assert hits >= 0.9 * 120
            modes.append(label)
        assert len(set(modes)) == 3
        assert (labels[360:] == -1).sum() >= 0.8 * 60
        assert 0 <= similarity.min() and similarity.max() <= 1

    def test_same_units_with_a_different_carry_are_different_comps(self):
        rng = random.Random(2)
        units = [f"S{i}" for i in range(8)]
        rows = comp_rows(rng, "X", 0, 120, 0, units) + comp_rows(rng, "X", 1, 120, 120, units)
        boards = build_boards(rows)

        labels, _ = assign(boards.vectors, fit_clusters(boards.vectors, min_cluster_size=20))

        first, second = (label_counts(labels, s, 120).most_common(1)[0][0] for s in (0, 120))
        assert first >= 0 and second >= 0 and first != second

    def test_comp_ids_survive_a_different_sample(self):
        rng = random.Random(3)
        rows = comp_rows(rng, "A", 0, 150, 0) + comp_rows(rng, "B", 2, 150, 150)
        boards = build_boards(rows)

        def comp_ids(seed):
            clusters = fit_clusters(
                boards.vectors, sample_size=200, min_cluster_size=20, seed=seed
            )
            labels, similarity = assign(boards.vectors, clusters)
            comps, _ = summarize(boards, labels, similarity, {}, PATCH, clusters.sample_size)
            return {c["comp_id"] for c in comps}

        assert comp_ids(0) == comp_ids(7)
        assert len(comp_ids(0)) == 2

    def test_a_blob_of_unrelated_boards_is_not_a_comp(self):
        rng = random.Random(1)
        rows = comp_rows(rng, "A", 0, 120, 0) + noise_rows(rng, 80, 120)
        boards = build_boards(rows)

        clusters = fit_clusters(boards.vectors, min_cluster_size=20)

        assert len(clusters.centroids) == 1
        assert clusters.thresholds.min() >= compositions.MIN_COHESION

    def test_nothing_to_cluster(self):
        assert fit_clusters(build_boards([]).vectors) is None
        few = build_boards([row(i, [feature("Ahri")]) for i in range(5)])
        assert fit_clusters(few.vectors) is None


class TestSummarize:
    def boards(self):
        carry_board = [feature("Ahri", items=3, star=3), feature("Nami", star=1), trait("Mage", 4)]
        return build_boards(
            [
                row(0, carry_board, placement=1, match=0),
                row(1, carry_board, placement=3, match=0),
                row(2, [feature("Ahri", items=2, star=2), trait("Mage", 2)], placement=8, match=1),
                row(3, [feature("Zed")], placement=2, match=2),
            ]
        )

    def summary(self, labels, names=None):
        boards = self.boards()
        similarity = np.full(len(boards), 0.9, dtype=np.float32)
        return summarize(
            boards, np.array(labels), similarity, names or {}, PATCH, 99
        )

    def test_counters_are_exact(self):
        (comp,), assignments = self.summary([0, 0, 0, -1])

        assert comp["boards"] == 3
        assert comp["matches"] == 2
        assert comp["placement_sum"] == 1 + 3 + 8
        assert comp["top4_count"] == 2
        assert comp["win_count"] == 1
        assert comp["sample_size"] == 99
        assert comp["patch"] == PATCH

    def test_unit_and_trait_summaries(self):
        (comp,), _ = self.summary([0, 0, 0, -1])

        ahri, nami = comp["units"]
        assert ahri == {"api_name": "Ahri", "frequency": 1.0, "avg_items": 2.6667, "avg_star": 2.6667}
        # Only two of the three boards had Nami
        assert nami["api_name"] == "Nami"
        assert nami["frequency"] == pytest.approx(0.6667, abs=1e-4)
        assert comp["traits"] == [{"api_name": "Mage", "frequency": 1.0, "avg_tier": 3.3333}]

    def test_carries_and_label_use_display_names(self):
        (comp,), _ = self.summary([0, 0, 0, -1], {"Ahri": "Ahri", "Mage": "Arcanist"})

        assert comp["carries"] == ["Ahri"]
        assert comp["label"] == "Arcanist Ahri"

    def test_label_falls_back_to_the_api_name(self):
        boards = build_boards([row(0, [feature("DA_18_KhaZix", items=3), trait("DA_Trait", 2)])])
        (comp,), _ = summarize(
            boards, np.array([0]), np.array([1.0], dtype=np.float32), {}, PATCH, 1
        )

        assert comp["label"] == "Trait KhaZix"

    def test_only_assigned_boards_get_an_assignment_row(self):
        _, assignments = self.summary([0, 0, 0, -1])

        assert [a["match_id"] for a in assignments] == ["NA1_0", "NA1_0", "NA1_1"]
        assert {a["comp_id"] for a in assignments} == {self.summary([0, 0, 0, -1])[0][0]["comp_id"]}
        assert assignments[0] == {
            "match_id": "NA1_0",
            "puuid": "puuid0",
            "played_at": "2026-09-28T12:00:00+00:00",
            "patch": PATCH,
            "comp_id": assignments[0]["comp_id"],
            "similarity": 0.9,
        }

    def test_comps_with_the_same_core_get_distinct_ids_biggest_first(self):
        same = [feature("Ahri", items=3), feature("Nami"), trait("Mage", 2)]
        boards = build_boards([row(i, same) for i in range(5)])
        labels = np.array([0, 1, 1, 1, 0])

        comps, _ = summarize(
            boards, labels, np.ones(5, dtype=np.float32), {}, PATCH, 5
        )

        # Biggest first: the 3-board comp keeps the plain id, the 2-board one gets "-2"
        bigger, smaller = comps
        assert (bigger["boards"], smaller["boards"]) == (3, 2)
        assert smaller["comp_id"] == f"{bigger['comp_id']}-2"
        assert "-" not in bigger["comp_id"]

    def test_no_assigned_boards(self):
        comps, assignments = self.summary([-1, -1, -1, -1])

        assert comps == [] and assignments == []


class TestWrite:
    def rows(self):
        boards = TestSummarize().boards()
        return summarize(
            boards,
            np.array([0, 0, 0, -1]),
            np.full(len(boards), 0.9, dtype=np.float32),
            {},
            PATCH,
            4,
        )

    def test_replaces_the_patch_in_one_transaction(self, fake_bq):
        comps, assignments = self.rows()

        write_compositions(fake_bq, PATCH, comps, assignments)

        (script, params), = fake_bq.queries
        assert script.startswith("BEGIN TRANSACTION;")
        assert script.rstrip().endswith("COMMIT TRANSACTION;")
        assert [(p.name, p.value) for p in params] == [("patch", PATCH)]
        for table in ("compositions", "participant_compositions"):
            delete = f"DELETE FROM `test-project.tft.{table}` WHERE patch = @patch;"
            assert delete in script
            assert script.index(delete) < script.index(f"INSERT INTO `test-project.tft.{table}`")
        assert len(fake_bq.staged("compositions")) == 1
        assert len(fake_bq.staged("participant_compositions")) == 3
        assert len(fake_bq.deleted) == 2  # both staging tables dropped

    def test_a_patch_with_no_assignments_is_still_cleared(self, fake_bq):
        write_compositions(fake_bq, PATCH, [], [])

        (script, _), = fake_bq.queries
        assert script.count("DELETE FROM") == 2
        assert "INSERT INTO" not in script


class TestClusterPatch:
    def feed(self, fake_bq, monkeypatch, rows):
        monkeypatch.setattr(compositions, "fetch_names", lambda client: {})
        fake_bq.query_rows = rows

    def synthetic(self):
        rng = random.Random(4)
        return comp_rows(rng, "A", 0, 100, 0) + comp_rows(rng, "B", 0, 100, 100)

    def test_writes_the_comps(self, fake_bq, monkeypatch):
        self.feed(fake_bq, monkeypatch, self.synthetic())

        comps = cluster_patch(fake_bq, PATCH, min_cluster_size=20)

        assert len(comps) == 2
        assert sum(c["boards"] for c in comps) <= 200
        assert len(fake_bq.staged("compositions")) == 2
        assert any("DELETE FROM" in sql for sql, _ in fake_bq.queries)

    def test_dry_run_writes_nothing(self, fake_bq, monkeypatch):
        self.feed(fake_bq, monkeypatch, self.synthetic())

        comps = cluster_patch(fake_bq, PATCH, min_cluster_size=20, dry_run=True)

        assert len(comps) == 2
        assert fake_bq.loads == {}
        assert not any("DELETE FROM" in sql for sql, _ in fake_bq.queries)

    def test_no_boards_leaves_the_previous_result_alone(self, fake_bq, monkeypatch):
        self.feed(fake_bq, monkeypatch, [])

        assert cluster_patch(fake_bq, PATCH) == []
        assert fake_bq.loads == {}
        assert not any("DELETE FROM" in sql for sql, _ in fake_bq.queries)


@pytest.mark.integration
class TestBoardsSqlCompiles:
    """Dry-runs the boards query against the real dataset. Free and reads nothing.

    Needs Application Default Credentials and the Terraform in infra/gcp applied.
    """

    def test_boards_query(self):
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError
        from google.cloud import bigquery

        from db.bq import make_client, table_ref

        try:
            google.auth.default()
        except DefaultCredentialsError:
            pytest.skip("no Google Application Default Credentials")
        client = make_client()
        sql = BOARDS_SQL.format(
            **{
                name: table_ref(client, name)
                for name in ("unit_items", "participant_units", "participant_traits", "participants", "matches")
            }
        )

        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                dry_run=True,
                use_query_cache=False,
                query_parameters=[bigquery.ScalarQueryParameter("patch", "STRING", PATCH)],
            ),
        )

        assert [f.name for f in job.schema] == ["match_id", "puuid", "played_at", "placement", "features"]
