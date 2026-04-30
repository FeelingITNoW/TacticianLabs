def get_all_unit_db_entries(supabase_client, unit_name):
    # should return all instances of a unit appearing in database
    response = (
        supabase_client.table("units")
        .select("*")
        .eq("character_id", unit_name)
        .execute()
    )
    return response.data


def get_all_active_trait_db_entries(supabase_client, trait_name):
    # should return all instances of a trait appearing in database
    response = (
        supabase_client.table("traits")
        .select("*")
        .eq("name", trait_name)
        .gt("tier_current", 0)
        .execute()
    )
    return response.data


def get_all_participants_with_unit(supabase_client, unit_name):
    # should return all matches where a unit with the given name appears
    db_entries = get_all_unit_db_entries(supabase_client, unit_name)
    unit_pairs = {(entry["match_id"], entry["puuid"]) for entry in db_entries}
    match_ids = list({entry["match_id"] for entry in db_entries})

    chunk_size = 50
    all_participants = []
    for i in range(0, len(match_ids), chunk_size):
        chunk = match_ids[i : i + chunk_size]
        response = (
            supabase_client.table("participants")
            .select("*")
            .in_("match_id", chunk)
            .execute()
        )
        all_participants.extend(response.data)

    return [p for p in all_participants if (p["match_id"], p["puuid"]) in unit_pairs]


def get_all_participants_with_trait(supabase_client, trait_name):
    # should return all matches where a trait with the given name appears
    db_entries = get_all_active_trait_db_entries(supabase_client, trait_name)
    trait_pairs = {(entry["match_id"], entry["puuid"]) for entry in db_entries}
    match_ids = list({entry["match_id"] for entry in db_entries})

    chunk_size = 50
    all_participants = []
    for i in range(0, len(match_ids), chunk_size):
        chunk = match_ids[i : i + chunk_size]
        response = (
            supabase_client.table("participants")
            .select("*")
            .in_("match_id", chunk)
            .execute()
        )
        all_participants.extend(response.data)

    return [p for p in all_participants if (p["match_id"], p["puuid"]) in trait_pairs]


def calculate_unit_win_rate(supabase_client, unit_name):
    # should calculate the win rate of matches where a unit with the given name appears
    db_entries = get_all_participants_with_unit(supabase_client, unit_name)
    match_ids = list({entry["match_id"] for entry in db_entries})
    if not match_ids:
        return 0

    entries_that_won = [entry for entry in db_entries if entry["placement"] == 1]
    return len(entries_that_won) / len(match_ids)


def calculate_unit_top4_rate(supabase_client, unit_name):
    # should calculate the top 4 rate of matches where a unit with the given name appears
    db_entries = get_all_participants_with_unit(supabase_client, unit_name)
    if not db_entries:
        return 0

    entries_that_top4d = [entry for entry in db_entries if entry["placement"] <= 4]
    return len(entries_that_top4d) / len(db_entries)


def calculate_unit_average_placement(supabase_client, unit_name):
    # should calculate the average placement of matches where a unit with the given name appears
    db_entries = get_all_participants_with_unit(supabase_client, unit_name)
    if not db_entries:
        return 0
    total_placement = sum(entry["placement"] for entry in db_entries)
    return total_placement / len(db_entries)


def calculate_trait_win_rate(supabase_client, trait_name):
    # should calculate the win rate of matches where a trait with the given name appears
    db_entries = get_all_participants_with_trait(supabase_client, trait_name)
    match_ids = list({entry["match_id"] for entry in db_entries})
    if not match_ids:
        return 0
    entries_that_won = [entry for entry in db_entries if entry["placement"] == 1]
    return len(entries_that_won) / len(match_ids)


def calculate_trait_top4_rate(supabase_client, trait_name):
    # should calculate the top 4 rate of matches where a trait with the given name appears
    db_entries = get_all_participants_with_trait(supabase_client, trait_name)
    if not db_entries:
        return 0
    entries_that_top4d = [entry for entry in db_entries if entry["placement"] <= 4]
    return len(entries_that_top4d) / len(db_entries)


def calculate_trait_average_placement(supabase_client, trait_name):
    # should calculate the average placement of matches where a trait with the given name appears
    db_entries = get_all_participants_with_trait(supabase_client, trait_name)
    if not db_entries:
        return 0
    total_placement = sum(entry["placement"] for entry in db_entries)
    return total_placement / len(db_entries)
