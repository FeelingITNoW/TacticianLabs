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
