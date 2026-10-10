"""The reference seed reads the committed Data Dragon files, so check them directly."""

from db.seed_reference_data import (
    SET_ID_PREFIX,
    _load_champions,
    _load_items,
    _load_traits,
)


class TestSetEighteenReferenceData:
    def test_champions(self):
        champions = _load_champions()

        assert len(champions) == 74
        assert all(c["api_name"].startswith(SET_ID_PREFIX) for c in champions)
        assert "DA_18_KhaZix" in {c["api_name"] for c in champions}

    def test_traits(self):
        traits = _load_traits()

        assert len(traits) == 36
        assert "DA_18_Brawler" in {t["api_name"] for t in traits}

    def test_items(self):
        items = _load_items()

        assert len(items) == 156
        assert {"DA_ArchangelsStaff", "DA_Component_RecurveBow"} <= {
            i["api_name"] for i in items
        }

    def test_item_types_come_from_the_api_name(self):
        from db.seed_reference_data import item_type

        assert item_type("DA_Artifact_Fishbones") == "artifact"
        assert item_type("DA_Item_Artifact_TalismanOfAscension") == "artifact"
        assert item_type("DA_BloodthirsterRadiant") == "radiant"
        assert item_type("DA_GargoyleStoneplate_Radiant") == "radiant"
        assert item_type("DA_Component_BFSword") == "component"
        assert item_type("DA_18_EmblemBrawler") == "emblem"
        assert item_type("DA_Bloodthirster") == "other"
        # A chest that contains radiants, not a radiant itself
        assert item_type("DA_RadiantLuckyItemChest") == "other"

    def test_every_item_has_a_type_and_the_counts_match_the_data(self):
        from collections import Counter

        counts = Counter(i["item_type"] for i in _load_items())

        assert set(counts) == {"artifact", "radiant", "component", "emblem", "other"}
        assert counts["component"] == 10
        assert counts["artifact"] >= 27
        assert counts["radiant"] >= 30

    def test_api_names_are_unique(self):
        for rows in (_load_champions(), _load_traits(), _load_items()):
            names = [r["api_name"] for r in rows]
            assert len(names) == len(set(names))


class TestMergeReferenceSql:
    def test_upserts_without_deleting(self, fake_bq):
        from db.seed_reference_data import merge_reference_sql

        sql = merge_reference_sql(fake_bq, "champions", "test-project.tft_staging.champions_x")

        assert sql.startswith("MERGE `test-project.tft.champions` AS t")
        assert "ON t.api_name = s.api_name" in sql
        assert "UPDATE SET name = s.name, cost = s.cost" in sql
        assert "INSERT (api_name, name, cost) VALUES (s.api_name, s.name, s.cost)" in sql
        assert "DELETE" not in sql


    def test_items_are_merged_with_their_type(self, fake_bq):
        from db.seed_reference_data import merge_reference_sql

        sql = merge_reference_sql(fake_bq, "items", "test-project.tft_staging.items_x")

        assert "UPDATE SET name = s.name, item_type = s.item_type" in sql


class TestSeedReferenceData:
    def test_refreshes_the_stored_names_after_merging(self, fake_bq):
        from db.seed_reference_data import seed_reference_data

        seed_reference_data(fake_bq)

        sqls = [sql for sql, _ in fake_bq.queries]
        assert [s.split("`")[1] for s in sqls[:3]] == [
            "test-project.tft.champions",
            "test-project.tft.traits",
            "test-project.tft.items",
        ]
        assert "UPDATE `test-project.tft.participant_units`" in sqls[-1]
        assert "UPDATE `test-project.tft.unit_items`" in sqls[-1]
