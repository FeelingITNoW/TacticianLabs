import os
import time
from dotenv import load_dotenv
from supabase import create_client, Client

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


def parse_composition_data(match_data: dict, client: Client):
    # Fields needed for match table:
    # - match_id (from file name)
    # - tft_set_number 
    # - patch_number
    # - region (from file name)
    match_id = match_data["metadata"]["match_id"]
    match_uuid = match_id
    tft_set_number = match_data["info"]["tft_set_number"]
    patch_number = float(match_data["info"]["game_version"].split(" ")[2][0:4])
    prepare_match_table(tft_set_number, patch_number, client, match_uuid)
    
    # - match_id (from file name)
    # player id 
    # placement
    # level
    participants = match_data["info"]["participants"]
    for participant in participants:
        player_id = participant["puuid"]
        placement = participant["placement"]
        level = participant["level"]
        composition_to_upload = {
            "match_id": match_uuid,
            "player_id": player_id,
            "placement": placement,
            "level": level    
        }
        composition_id = prepare_composition_table(client, composition_to_upload)
        if composition_id is None:
            continue
        units = participant["units"]
        traits = participant["traits"]
        
        # Uploading traits to databse, utilize composition_id as foreign key to link traits to composition
        for trait in traits:
            trait_to_upload = {
                "composition_id": composition_id,
                "name": trait['name'],
                "current_tier": trait['tier_current'],
                "num_units": trait['num_units'],
                "style": trait['style'],
                "tier_total": trait['tier_total']
            }
            try:
                response = (
                    client.table("traits")
                    .insert(trait_to_upload)
                )
                _execute_with_retry(response)
            except Exception as e:
                # PostgreSQL duplicate key error code is 23505, if the trait already exists in the database, we can skip it and move on to the next one
                if "23505" in str(e):
                    #do nothing, the trait already exists in the database
                    pass
                else:
                    raise
        # Uploading units to database, utilize composition_id as foreign key to link units to composition
        for unit in units:
            unit_to_upload = {
                "composition_id": composition_id,
                "character_id": unit['character_id'],
                "tier": unit['tier'],
                "rarity": unit['rarity'],
                "items": unit['itemNames']
            }
            try:
                response = (
                    client.table("unit")
                    .insert(unit_to_upload)
                )
                _execute_with_retry(response)
            except Exception as e:
                # PostgreSQL duplicate key error code is 23505, if the unit already exists in the database, we can skip it and move on to the next one
                if "23505" in str(e):
                    #do nothing, the unit already exists in the database
                    pass
                else:
                    raise

def prepare_composition_table(client: Client, composition_dict: dict):
    try:
        response = _execute_with_retry(
            client.table("composition")
            .insert(composition_dict)
        )
    except Exception as e: 
        # PostgreSQL duplicate key error code is 23505, if the composition already exists in the database, we can skip it and move on to the next one
        if "23505" in str(e):
            existing = _execute_with_retry(
                client.table("composition")
                .select("id")
                .eq("match_id", composition_dict["match_id"])
                .eq("player_id", composition_dict["player_id"])
                .limit(1)
            )
            if existing.data:
                return existing.data[0]["id"]
            return None
        else:
            raise
    return response.data[0]['id']

def prepare_match_table(tft_set_number: int, patch_number: float, client: Client, match_uuid: str):
    try:
        response = _execute_with_retry(
            client.table("match")
            .insert({"set": tft_set_number, "patch": patch_number, "uuid": match_uuid})
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
    parse_composition_data("../files/match/SG2_134655367.json", client=supabase)