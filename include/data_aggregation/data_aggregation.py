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


def get_all_units_with_item(supabase_client, item_name):
    response = (
        supabase_client.table("units")
        .select("*")
        .contains("item_names", [item_name])
        .execute()
    )

    return response.data


def _fetch_participants_for_entries(supabase_client, db_entries):
    """Fetch participant rows matching the (match_id, puuid) pairs in db_entries."""
    pairs = {(entry["match_id"], entry["puuid"]) for entry in db_entries}
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

    return [p for p in all_participants if (p["match_id"], p["puuid"]) in pairs]


def _calculate_stat(participants, stat, total_participants=None):
    """
    Calculate a stat from a list of participant rows.

    win_rate and top4_rate divide by unique match count (one entry per match).
    average_placement divides by participant count (mirrors the fetch — one row per participant).
    play_rate requires total_participants to be provided.
    """
    if not participants:
        return 0
    match_count = len({p["match_id"] for p in participants})
    if stat == "win_rate":
        return len([p for p in participants if p["placement"] == 1]) / match_count
    if stat == "top4_rate":
        return len([p for p in participants if p["placement"] <= 4]) / len(participants)
    if stat == "average_placement":
        return sum(p["placement"] for p in participants) / len(participants)
    if stat == "play_rate":
        if total_participants is None:
            raise ValueError("total_participants must be provided for play_rate")
        return len(participants) / total_participants
    raise ValueError(f"Unknown stat: {stat}")


def get_num_of_all_participants(supabase_client):
    response = supabase_client.table("participants").select("*").execute()
    return len(response.data)


def get_all_participants_with_unit(supabase_client, unit_name):
    return _fetch_participants_for_entries(
        supabase_client, get_all_unit_db_entries(supabase_client, unit_name)
    )


def get_all_participants_with_trait(supabase_client, trait_name):
    return _fetch_participants_for_entries(
        supabase_client, get_all_active_trait_db_entries(supabase_client, trait_name)
    )


def get_all_participants_with_item(supabase_client, item_name):
    return _fetch_participants_for_entries(
        supabase_client, get_all_units_with_item(supabase_client, item_name)
    )


def calculate_unit_win_rate(supabase_client, unit_name):
    return _calculate_stat(
        get_all_participants_with_unit(supabase_client, unit_name),
        "win_rate",
    )


def calculate_unit_top4_rate(supabase_client, unit_name):
    return _calculate_stat(
        get_all_participants_with_unit(supabase_client, unit_name),
        "top4_rate",
    )


def calculate_unit_average_placement(supabase_client, unit_name):
    return _calculate_stat(
        get_all_participants_with_unit(supabase_client, unit_name),
        "average_placement",
    )


def calculate_unit_play_rate(supabase_client, unit_name):
    participants = get_all_participants_with_unit(supabase_client, unit_name)
    total = get_num_of_all_participants(supabase_client)
    return _calculate_stat(participants, "play_rate", total_participants=total)


def calculate_trait_win_rate(supabase_client, trait_name):
    return _calculate_stat(
        get_all_participants_with_trait(supabase_client, trait_name),
        "win_rate",
    )


def calculate_trait_top4_rate(supabase_client, trait_name):
    return _calculate_stat(
        get_all_participants_with_trait(supabase_client, trait_name),
        "top4_rate",
    )


def calculate_trait_average_placement(supabase_client, trait_name):
    return _calculate_stat(
        get_all_participants_with_trait(supabase_client, trait_name),
        "average_placement",
    )


def calculate_trait_play_rate(supabase_client, trait_name):
    participants = get_all_participants_with_trait(supabase_client, trait_name)
    total = get_num_of_all_participants(supabase_client)
    return _calculate_stat(participants, "play_rate", total_participants=total)


def calculate_item_win_rate(supabase_client, item_name):
    return _calculate_stat(
        get_all_participants_with_item(supabase_client, item_name),
        "win_rate",
    )


def calculate_item_top4_rate(supabase_client, item_name):
    return _calculate_stat(
        get_all_participants_with_item(supabase_client, item_name),
        "top4_rate",
    )


def calculate_item_average_placement(supabase_client, item_name):
    return _calculate_stat(
        get_all_participants_with_item(supabase_client, item_name),
        "average_placement",
    )


def calculate_item_play_rate(supabase_client, item_name):
    participants = get_all_participants_with_item(supabase_client, item_name)
    total = get_num_of_all_participants(supabase_client)
    return _calculate_stat(participants, "play_rate", total_participants=total)
