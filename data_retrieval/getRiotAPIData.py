from datetime import datetime
import asyncio
import sys
import time
import uuid
import requests
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client
from transformData import parse_composition_data, prepare_composition_table, prepare_match_table

# Load .env from repository root no matter where this script is run from.
REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=REPO_ROOT / ".env")

RIOT_API_KEY = os.getenv("RIOT_API_KEY") or os.getenv("API_KEY")
SECONDS_IN_A_DAY = 86400
LOCAL_STORAGE_DIRECTORY = "../files/match"
RANK_TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"]
RANK_DIVISIONS = ["I", "II", "III", "IV"]      
RIOT_REGIONS = [
    "BR1",
    "EUN1",
    "EUW1",
    "JP1",
    "KR",
    "LA1",
    "LA2",
    "NA1",
    "OC1",
    "PH2",
    "SG2",
    "TH2",
    "TW2",
    "VN2"
]

# Riot platform-to-routing region mapping
RIOT_REGIONS_MAP = {
    # Americas
    "NA1": "AMERICAS",
    "BR1": "AMERICAS",
    "LA1": "AMERICAS",
    "LA2": "AMERICAS",

    # Europe
    "EUW1": "EUROPE",
    "EUN1": "EUROPE",
    "TR1": "EUROPE",
    "RU": "EUROPE",

    # Asia
    "KR": "ASIA",
    "JP1": "ASIA",

    # Southeast Asia (SEA)
    "PH2": "SEA",
    "SG2": "SEA",
    "TH2": "SEA",
    "TW2": "SEA",
    "VN2": "SEA",
}


def riot_match_uuid(match_id: str) -> str:
    """Create a deterministic UUID from Riot's match id string."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"riot:tft:match:{match_id}"))


def _ensure_riot_api_key() -> None:
    if RIOT_API_KEY:
        return
    raise RuntimeError(
        "Riot API key not found. Set RIOT_API_KEY (preferred) or API_KEY in .env"
    )


def riot_get(url: str, params: dict | None = None):
    _ensure_riot_api_key()
    request_params = dict(params or {})
    request_params["api_key"] = RIOT_API_KEY
    response = requests.get(url=url, params=request_params, timeout=30)
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        if response.status_code == 401:
            raise RuntimeError(
                "Riot API returned 401 Unauthorized. Your key is missing, expired, or invalid. "
                "Generate a fresh key at https://developer.riotgames.com/, then update .env with "
                "RIOT_API_KEY=RGAPI-..."
            ) from exc
        raise
    return response


def get_match_history(puuid: str, region: str, start_index=0, end_index=20):
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?start={start_index}&count={end_index}"
    response = riot_get(url=match_history_url)
    return response.json()

def get_match_history_by_date(puuid: str, date: datetime, start_index=0, count=20):
    epoch_seconds_start = int(date.timestamp())
    epoch_seconds_end = epoch_seconds_start + SECONDS_IN_A_DAY
    match_history_url = f"https://sea.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {
        "startTime": epoch_seconds_start,
        "endTime": epoch_seconds_end,
        "count": count
    }
    response = riot_get(url=match_history_url, params=params)
    return response.json()

def get_last_100_matches(puuid: str, region: str):
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {
        "count": 100
    }
    response = riot_get(url=match_history_url, params=params)
    return response.json()
    
def get_challengers(region: str):
    HTTP_GET_CHALLENGERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT"
    response = riot_get(url=HTTP_GET_CHALLENGERS_API_URL)
    challengers = response.json()['entries']
    return challengers

def get_grandmasters(region: str):
    HTTP_GET_GRANDMASTERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/grandmaster?queue=RANKED_TFT"
    response = riot_get(url=HTTP_GET_GRANDMASTERS_API_URL)
    grandmasters = response.json()['entries']
    return grandmasters

def get_masters(region: str):
    HTTP_GET_MASTERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/master?queue=RANKED_TFT"
    response = riot_get(url=HTTP_GET_MASTERS_API_URL)
    masters = response.json()['entries']
    return masters

async def get_all_players_below_masters(region: str, tier=None, division=None):
    # Tiers:  IRON, BRONZE, SILVER, GOLD, PLATINUM, EMERALD, DIAMOND
    # Divisions: I, II, III, IV
    players = []
    for tier in RANK_TIERS:
        for division in RANK_DIVISIONS:
            page = 1
            while True:
                await asyncio.sleep(2)
                url = f"https://{region}.api.riotgames.com/tft/league/v1/entries/{tier}/{division}"
                params = {"queue": "RANKED_TFT", "page": page}
                
                response = riot_get(url=url, params=params)
                data = response.json()

                if not data:  # stop when no more players on this page
                    break

                players.extend(data)  # append all players from this page
                page += 1       
                print(f"page {page}")
            print(f"done with {tier} {division}")
    return players

def riot_get_with_retry(url: str, params: dict | None = None, max_retries: int = 5):
    """Wraps riot_get with exponential backoff for 429 (rate-limited) and transient network errors."""
    delay = 1
    for attempt in range(max_retries):
        try:
            return riot_get(url=url, params=params)
        except requests.HTTPError as exc:
            if exc.response.status_code == 429:
                retry_after = int(exc.response.headers.get("Retry-After", delay))
                print(f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(retry_after)
                delay = min(delay * 2, 120)
            else:
                raise
        except requests.ConnectionError as exc:
            if attempt < max_retries - 1:
                print(f"Network error, retrying in {delay}s (attempt {attempt + 1}/{max_retries}): {exc}")
                time.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise
    raise RuntimeError(f"All {max_retries} retries exhausted for {url}")


def get_match_data(match_id: str, region: str):
    get_match_data_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/{match_id}"
    response = riot_get_with_retry(url=get_match_data_url)
    return response.json()

def prepare_player_data(puuid: str, region: str, client: Client):
    api_region_map = {
        "NA1": "AMERICAS",
        "BR1": "AMERICAS",
        "LA1": "AMERICAS",
        "LA2": "AMERICAS",

        # Europe
        "EUW1": "EUROPE",
        "EUN1": "EUROPE",
        "TR1": "EUROPE",
        "RU": "EUROPE",

        # Asia
        "KR": "ASIA",
        "JP1": "ASIA",

        # Southeast Asia (SEA)
        "PH2": "ASIA",
        "SG2": "ASIA",
        "TH2": "ASIA",
        "TW2": "ASIA",
        "VN2": "ASIA",
    }
    mapped_region = api_region_map.get(region)
    account_data = get_account_name_from_puuid(puuid=puuid, region=mapped_region)
    league_data = get_player_league_data(puuid=puuid, region=region)
    player_dict = dict()
    player_dict["uuid"] = puuid
    player_dict["tier"] = league_data[0]["tier"] if league_data else "UNRANKED"
    player_dict["division"] = league_data[0]["rank"] if league_data else "UNRANKED"
    player_dict["LP"] = league_data[0]["leaguePoints"] if league_data else 0
    player_dict["region"] = region
    player_dict["player_name"] = account_data["gameName"] + "#" + account_data["tagLine"]

    try:
        response = (
            client.table("player")
            .insert(player_dict)
            .execute()
        )
    except Exception as e: 
        # PostgreSQL duplicate key error code is 23505, if the player already exists in the database, we can skip it and move on to the next one
        if "23505" in str(e):   
            #do nothing, the player already exists in the database
            pass    
        else:
            raise
    return player_dict 


def get_account_name_from_puuid(puuid: str, region: str):
    get_summoner_data_url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}"
    response = riot_get_with_retry(url=get_summoner_data_url)
    return response.json()

def get_player_league_data(puuid:str, region: str):
    get_league_data_url = f"https://{region}.api.riotgames.com/tft/league/v1/by-puuid/{puuid}"
    response = riot_get_with_retry(url=get_league_data_url)
    return response.json()

async def get_tiered_match_data(tier: str, region: str):
    if tier not in RANK_TIERS:
        return ["no tier specified"]
    if region not in RIOT_REGIONS:
        return ["invalid region"]

    players = []
    for division in RANK_DIVISIONS:
        page = 1
        while True:
            await asyncio.sleep(2)
            url = f"https://{region}.api.riotgames.com/tft/league/v1/entries/{tier}/{division}"
            params = {"queue": "RANKED_TFT", "page": page}
            response = riot_get(url=url, params=params)
            data = response.json()

            if not data:  # stop when no more players on this page
                break

            players.extend(data)  # append all players from this page
            page += 1       
    return players

def populate_player_table_with_tiered_data(region: str, client: Client):
    for player in get_challengers(region=region):
        prepare_player_data(puuid=player["puuid"], region=region, client=client)
    for player in get_grandmasters(region=region):
        prepare_player_data(puuid=player["puuid"], region=region, client=client)
    for player in get_masters(region=region):
        prepare_player_data(puuid=player["puuid"], region=region, client=client)
    

async def get_challenger_match_data(region: str, client: Client) -> None:
    match_region_string = RIOT_REGIONS_MAP[region]

    # --- Phase 1: collect all unique new match IDs from every challenger ---
    challengers = get_challengers(region=region)
    matches_in_db_response = (client.table("match").select("uuid").execute())
    matches_in_db = matches_in_db_response.data

    new_match_ids: list[str] = []
    for challenger in challengers:
        puuid = challenger["puuid"]
        print(f"Fetching match history for challenger (PUUID: {puuid}) in region {region}...")
        last_100_matches = get_last_100_matches(region=match_region_string, puuid=puuid)
        if "status" in last_100_matches:
            sys.exit(0)
        for match_id in last_100_matches:
            if match_id not in [m["uuid"] for m in matches_in_db] and match_id not in new_match_ids:
                print('added match: ', match_id)
                new_match_ids.append(match_id)

    print(f"Collected {len(new_match_ids)} new match IDs. Fetching and uploading…")

    # --- Phase 2: fetch + upload concurrently, respecting Riot rate limits ---
    # Personal keys: 20 req/s, 100 req/2 min → conservative concurrency of 5
    semaphore = asyncio.Semaphore(5)
    loop = asyncio.get_event_loop()

    async def _fetch_and_upload(match_id: str) -> None:
        async with semaphore:
            match_data = await loop.run_in_executor(
                None,
                lambda mid=match_id: riot_get_with_retry(
                    url=f"https://{match_region_string}.api.riotgames.com/tft/match/v1/matches/{mid}"
                ).json(),
            )
            parse_composition_data(
                match_data=match_data, client=client
            )
            print(f"Uploaded {match_id}")

    await asyncio.gather(*[_fetch_and_upload(mid) for mid in new_match_ids])



if __name__ == "__main__":
    _url: str = os.environ.get("supabase_url")
    _key: str = os.environ.get("supabase_key")
    _client: Client = create_client(_url, _key)
    asyncio.run(get_challenger_match_data("SG2", _client))