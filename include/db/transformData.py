import os
import time
from dotenv import load_dotenv
from supabase import create_client, Client

from riot_api.constants import TFT_RANKED_QUEUE_ID
load_dotenv()


def _is_transient_supabase_error(exc: Exception) -> bool:
    text = str(exc)
    name = exc.__class__.__name__
    return (
        "RemoteProtocolError" in name
        or "ConnectTimeout" in name
        or "ReadTimeout" in name
        or "ConnectionTerminated" in text
        or "Server disconnected" in text
        or "'code': 429" in text
        or '"code": 429' in text
        or "'code': 502" in text
        or '"code": 502' in text
        or "'code': 503" in text
        or '"code": 503' in text
        or "'code': 504" in text
        or '"code": 504' in text
        or "Bad gateway" in text
        or "JSON could not be generated" in text
    )


def _execute_with_retry(builder, max_retries: int = 6):
    delay = 0.5
    for attempt in range(max_retries):
        try:
            return builder.execute()
        except Exception as exc:
            if attempt < max_retries - 1 and _is_transient_supabase_error(exc):
                time.sleep(delay)
                delay = min(delay * 2, 16)
                continue
            raise


def parse_match_data(match_data: dict, client: Client, latest_version: str):
    # If game is not ranked game, skip it 
    if match_data["info"]["queue_id"] != TFT_RANKED_QUEUE_ID:
        print(f"Skipping match {match_data['metadata']['match_id']} - not a ranked game (queue_id: {match_data['info']['queue_id']})")
        return
    
    
    # Fields needed for match table:
    # - match_id (from file name)
    # - tft_set_number 
    # - patch_number
    # - region (from file name)
    match_id = match_data["metadata"]["match_id"]
    match_uuid = match_id
    tft_set_number = match_data["info"]["tft_set_number"]
    patch_number = latest_version
    game_datetime = match_data["info"].get("game_datetime")
    game_length = match_data["info"].get("game_length")
    
    # - match_id (from file name)
    # player id 
    # placement
    # level
    participants = match_data["info"]["participants"]

    # Build all composition rows first, then upsert in a single batch flow.
    participant_rows: list[dict] = []
    trait_rows: list[dict] = []
    unit_rows: list[dict] = []
    for participant in participants:
        participant_rows.append(
            {
                "match_id": match_uuid,
                "puuid": participant["puuid"],
                "placement": participant["placement"],
                "level": participant["level"],
                "gold_left": participant["gold_left"],
                "last_round": participant["last_round"],
                "total_damage_to_players": participant["total_damage_to_players"],
            }
        )

        match_id = match_uuid
        puuid = participant["puuid"]

        for trait in participant["traits"]:
            trait_rows.append(
                {
                    "match_id": match_id,
                    "puuid": puuid,
                    "name": trait["name"],
                    "tier_current": trait["tier_current"],
                    "num_units": trait["num_units"],
                    "style": trait["style"],
                    "tier_total": trait["tier_total"],
                }
            )

        for unit in participant["units"]:
            unit_rows.append(
                {
                    "match_id": match_id,
                    "puuid": puuid,
                    "character_id": unit["character_id"],
                    "tier": unit["tier"],
                    "item_names": unit["itemNames"],
                    "rarity": unit["rarity"],
                }
            )

    # Deduplicate within batch to avoid ON CONFLICT affecting the same row twice
    seen_traits: dict = {}
    for row in trait_rows:
        seen_traits[(row["match_id"], row["puuid"], row["name"])] = row
    trait_rows = list(seen_traits.values())

    seen_units: dict = {}
    for row in unit_rows:
        seen_units[(row["match_id"], row["puuid"], row["character_id"])] = row
    unit_rows = list(seen_units.values())

    prepare_match_table(tft_set_number, patch_number, client, match_uuid, game_datetime, game_length)
    if participant_rows:
        _execute_with_retry(
            client.table("participants").insert(participant_rows)
        )

    # Batch upsert traits and units
    if trait_rows:
        _execute_with_retry(
            client.table("traits").insert(trait_rows)
        )
    if unit_rows:
        _execute_with_retry(
            client.table("units").insert(unit_rows)
        )
    
    

def prepare_match_table(tft_set_number: int, patch_number: float, client: Client, match_uuid: str, datetime: int, gamelength: float ):
    try:
        response = _execute_with_retry(
            client.table("matches")
            .upsert(
                    {   
                    "tft_set_number": tft_set_number, 
                    "game_version": patch_number, 
                     "match_id": match_uuid, 
                     "game_datetime": datetime, 
                     "game_length": gamelength
                     }
                )
        )
    except Exception as e: 
        # PostgreSQL duplicate key error code is 23505, if the match already exists in the database, we can skip it and move on to the next one
        if "23505" in str(e):
            #do nothing, the match already exists in the database
            pass
        else:
            raise

    return
    
if __name__ == "__main__":
    url: str = os.environ.get('supabase_url')
    key: str = os.environ.get('supabase_key')
    supabase: Client = create_client(url, key)