# baseline test to see that the seed data is loaded correctly
from data_aggregation.data_aggregation import (
    calculate_unit_win_rate,
    calculate_unit_top4_rate,
    calculate_unit_average_placement,
    calculate_trait_win_rate,
    calculate_trait_top4_rate,
    calculate_trait_average_placement,
    get_all_unit_db_entries,
    get_all_active_trait_db_entries,
    get_all_participants_with_unit,
    get_all_participants_with_trait,
)


class TestSeedDataLoaded:
    def test_seed_loaded_matches(self, local_supabase):
        result = (
            local_supabase.table("matches").select("match_id", count="exact").execute()
        )
        assert result.count > 0

    def test_seed_loaded_players(self, local_supabase):
        result = (
            local_supabase.table("players").select("puuid", count="exact").execute()
        )
        assert result.count > 0

    def test_seed_loaded_traits(self, local_supabase):
        result = (
            local_supabase.table("traits").select("match_id", count="exact").execute()
        )
        assert result.count > 0

    def test_seed_loaded_units(self, local_supabase):
        result = (
            local_supabase.table("units").select("match_id", count="exact").execute()
        )
        assert result.count > 0

    def test_seed_loaded_player_ranked_stats(self, local_supabase):
        result = (
            local_supabase.table("player_ranked_stats")
            .select("puuid", count="exact")
            .execute()
        )
        assert result.count > 0

    def test_seed_loaded_players_with_ranked_stats(self, local_supabase):
        result = (
            local_supabase.table("player_ranked_stats")
            .select("puuid", count="exact")
            .execute()
        )
        assert result.count > 0


class TestQueryScripts:
    def test_get_all_unit_db_entries(self, local_supabase):
        get_all_unit_db_entries_result = get_all_unit_db_entries(
            local_supabase, "TFT16_Swain"
        )

        # basic sanity check that results are returned and match the query criteria
        assert len(get_all_unit_db_entries_result) > 0

        # all returned entries should have the correct unit name
        assert all(
            entry["character_id"] == "TFT16_Swain"
            for entry in get_all_unit_db_entries_result
        )

        # should return all instances of the unit in the database, so count should match a direct query
        direct_query_result = (
            local_supabase.table("units")
            .select("character_id", count="exact")
            .eq("character_id", "TFT16_Swain")
            .execute()
        )
        assert len(get_all_unit_db_entries_result) == direct_query_result.count

    def test_get_all_participants_with_unit(self, local_supabase):
        get_all_unit_db_entries_result = get_all_unit_db_entries(
            local_supabase, "TFT16_Swain"
        )
        get_all_participants_with_unit_result = get_all_participants_with_unit(
            local_supabase, "TFT16_Swain"
        )
        # basic sanity check that results are returned and match the query criteria
        assert len(get_all_participants_with_unit_result) > 0

        # all returned entries should have the correct unit name
        db_entry_puuid_with_match_id = {
            (entry["puuid"], entry["match_id"])
            for entry in get_all_unit_db_entries_result
        }

        assert all(
            (entry["puuid"], entry["match_id"]) in db_entry_puuid_with_match_id
            for entry in get_all_participants_with_unit_result
        )

        # should return all matches where the unit appears, so count should match a direct query
        direct_query_result = (
            local_supabase.table("units")
            .select("character_id", count="exact")
            .eq("character_id", "TFT16_Swain")
            .execute()
        )
        assert len(get_all_participants_with_unit_result) == direct_query_result.count

    def test_calculate_unit_win_rate(self, local_supabase):
        calculate_unit_win_rate_result = calculate_unit_win_rate(
            local_supabase, "TFT16_Swain"
        )

        # basic sanity check that a result is returned and is between 0 and 1
        assert calculate_unit_win_rate_result is not None
        assert 0 <= calculate_unit_win_rate_result <= 1

        # mirror calculate_unit_win_rate exactly: get participants, derive unique match_ids, count wins
        db_entries = get_all_participants_with_unit(local_supabase, "TFT16_Swain")
        match_ids = list({entry["match_id"] for entry in db_entries})
        entries_that_won = [entry for entry in db_entries if entry["placement"] == 1]
        expected_win_rate = len(entries_that_won) / len(match_ids) if match_ids else 0

        assert calculate_unit_win_rate_result == expected_win_rate

    def test_calculate_unit_top4_rate(self, local_supabase):
        result = calculate_unit_top4_rate(local_supabase, "TFT16_Swain")

        assert result is not None
        assert 0 <= result <= 1

        db_entries = get_all_participants_with_unit(local_supabase, "TFT16_Swain")
        entries_top4 = [entry for entry in db_entries if entry["placement"] <= 4]
        expected = len(entries_top4) / len(db_entries) if db_entries else 0

        assert result == expected

    def test_calculate_unit_average_placement(self, local_supabase):
        result = calculate_unit_average_placement(local_supabase, "TFT16_Swain")

        assert result is not None
        assert 1 <= result <= 8

        db_entries = get_all_participants_with_unit(local_supabase, "TFT16_Swain")
        expected = (
            sum(entry["placement"] for entry in db_entries) / len(db_entries)
            if db_entries
            else 0
        )

        assert result == expected

    def test_get_all_active_trait_db_entries(self, local_supabase):
        result = get_all_active_trait_db_entries(local_supabase, "TFT16_Brawler")

        assert len(result) > 0
        assert all(entry["name"] == "TFT16_Brawler" for entry in result)
        assert all(entry["tier_current"] > 0 for entry in result)

        direct_query_result = (
            local_supabase.table("traits")
            .select("name", count="exact")
            .eq("name", "TFT16_Brawler")
            .gt("tier_current", 0)
            .execute()
        )
        assert len(result) == direct_query_result.count

    def test_get_all_participants_with_trait(self, local_supabase):
        trait_entries = get_all_active_trait_db_entries(local_supabase, "TFT16_Brawler")
        result = get_all_participants_with_trait(local_supabase, "TFT16_Brawler")

        assert len(result) > 0

        trait_pairs = {(entry["match_id"], entry["puuid"]) for entry in trait_entries}
        assert all(
            (entry["match_id"], entry["puuid"]) in trait_pairs for entry in result
        )

        assert len(result) == len(trait_entries)

    def test_calculate_trait_win_rate(self, local_supabase):
        result = calculate_trait_win_rate(local_supabase, "TFT16_Brawler")

        assert result is not None
        assert 0 <= result <= 1

        db_entries = get_all_participants_with_trait(local_supabase, "TFT16_Brawler")
        match_ids = {entry["match_id"] for entry in db_entries}
        entries_won = [entry for entry in db_entries if entry["placement"] == 1]
        expected = len(entries_won) / len(match_ids) if match_ids else 0

        assert result == expected

    def test_calculate_trait_top4_rate(self, local_supabase):
        result = calculate_trait_top4_rate(local_supabase, "TFT16_Brawler")

        assert result is not None
        assert 0 <= result <= 1

        db_entries = get_all_participants_with_trait(local_supabase, "TFT16_Brawler")
        entries_top4 = [entry for entry in db_entries if entry["placement"] <= 4]
        expected = len(entries_top4) / len(db_entries) if db_entries else 0

        assert result == expected

    def test_calculate_trait_average_placement(self, local_supabase):
        result = calculate_trait_average_placement(local_supabase, "TFT16_Brawler")

        assert result is not None
        assert 1 <= result <= 8

        db_entries = get_all_participants_with_trait(local_supabase, "TFT16_Brawler")
        expected = (
            sum(entry["placement"] for entry in db_entries) / len(db_entries)
            if db_entries
            else 0
        )

        assert result == expected
