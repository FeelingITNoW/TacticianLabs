from datetime import date, datetime, timedelta
import asyncio
import sys
import time
import uuid
import httpx
import os
from pathlib import Path
from dotenv import load_dotenv
from supabase import create_client, Client

# Load .env from repository root no matter where this script is run from.
REPO_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(dotenv_path=REPO_ROOT / ".env")

RIOT_API_KEY = os.getenv("RIOT_API_KEY") or os.getenv("API_KEY")
SECONDS_IN_A_DAY = 86400
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

def _ensure_riot_api_key() -> None:
    if RIOT_API_KEY:
        return
    raise RuntimeError(
        "Riot API key not found. Set RIOT_API_KEY (preferred) or API_KEY in .env"
    )

async def riot_get(client: httpx.AsyncClient, url: str, params: dict | None = None) -> httpx.Response:
    _ensure_riot_api_key()
    request_params = dict(params or {})
    request_params["api_key"] = RIOT_API_KEY
    response = await client.get(url, params=request_params, timeout=30)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if response.status_code == 401:
            raise RuntimeError(
                "Riot API returned 401 Unauthorized. Your key is missing, expired, or invalid. "
                "Generate a fresh key at https://developer.riotgames.com/, then update .env with "
                "RIOT_API_KEY=RGAPI-..."
            ) from exc
        raise
    return response


async def get_match_history(client: httpx.AsyncClient, puuid: str, region: str, start_index=0, end_index=20):
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?start={start_index}&count={end_index}"
    response = await riot_get(client, url=match_history_url)
    return response.json()

async def get_match_history_from_last_n_days(client: httpx.AsyncClient, puuid: str, startTime: int, region: str, start_index=0, count=100):
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {
        "startTime": startTime,
        "count": count
    }
    response = await riot_get(client, url=match_history_url, params=params)
    return response.json()

async def get_last_100_matches(client: httpx.AsyncClient, puuid: str, region: str):
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {
        "count": 100
    }
    response = await riot_get(client, url=match_history_url, params=params)
    return response.json()
    
async def get_challengers(client: httpx.AsyncClient, region: str):
    HTTP_GET_CHALLENGERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT"
    response = await riot_get(client, url=HTTP_GET_CHALLENGERS_API_URL)
    challengers = response.json()['entries']
    return challengers

async def get_grandmasters(client: httpx.AsyncClient, region: str):
    HTTP_GET_GRANDMASTERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/grandmaster?queue=RANKED_TFT"
    response = await riot_get(client, url=HTTP_GET_GRANDMASTERS_API_URL)
    grandmasters = response.json()['entries']
    return grandmasters

async def get_masters(client: httpx.AsyncClient, region: str):
    HTTP_GET_MASTERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/master?queue=RANKED_TFT"
    response = await riot_get(client, url=HTTP_GET_MASTERS_API_URL)
    masters = response.json()['entries']
    return masters

async def get_all_players_below_masters(client: httpx.AsyncClient, region: str, tier=None, division=None):
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
                
                response = await riot_get(client, url=url, params=params)
                data = response.json()

                if not data:  # stop when no more players on this page
                    break

                players.extend(data)  # append all players from this page
                page += 1       
                print(f"page {page}")
            print(f"done with {tier} {division}")
    return players

async def riot_get_with_retry(client: httpx.AsyncClient, url: str, params: dict | None = None, max_retries: int = 5) -> httpx.Response:
    """Wraps riot_get with exponential backoff for 429 (rate-limited) and transient network errors."""
    delay = 1
    for attempt in range(max_retries):
        try:
            return await riot_get(client, url=url, params=params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = int(exc.response.headers.get("Retry-After", delay))
                print(f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(retry_after)
                delay = min(delay * 2, 120)
            else:
                raise

        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:

            if attempt < max_retries - 1:
                print(f"Network error, retrying in {delay}s (attempt {attempt + 1}/{max_retries}): {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise
    raise RuntimeError(f"All {max_retries} retries exhausted for {url}")


async def get_match_data(client: httpx.AsyncClient, match_id: str, region: str):
    get_match_data_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/{match_id}"
    response = await riot_get_with_retry(client, url=get_match_data_url)
    return response.json()

async def prepare_player_data(client: httpx.AsyncClient, puuid: str, region: str, db_client: Client):
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
    account_data = await get_account_name_from_puuid(client, puuid=puuid, region=mapped_region)
    league_data = await get_player_league_data(client, puuid=puuid, region=region)
    player_ranked_stats_dict = dict()
    player_dict = dict() 
    player_ranked_stats_dict["puuid"] = puuid
    player_ranked_stats_dict["tier"] = league_data[0]["tier"] if league_data else "UNRANKED"
    player_ranked_stats_dict["rank"] = league_data[0]["rank"] if league_data else "UNRANKED"
    player_ranked_stats_dict["league_points"] = league_data[0]["leaguePoints"] if league_data else 0
    player_ranked_stats_dict["wins"] = league_data[0]["wins"] if league_data else 0
    player_ranked_stats_dict["losses"] = league_data[0]["losses"] if league_data else 0
    player_ranked_stats_dict["hot_streak"] = league_data[0]["hotStreak"] if league_data else False
    
    player_dict["puuid"] = puuid
    player_dict["game_name"] = account_data["gameName"] + "#" + account_data["tagLine"]
    player_dict["region"] = region
    player_dict["tag_line"] = account_data["tagLine"]

    try:
        player_response = (
            db_client.table("players")
            .upsert(player_dict)
            .execute()
        )

        player_ranked_stats_response = (
            db_client.table("player_ranked_stats")
            .upsert(player_ranked_stats_dict)
            .execute()
        )
        

    except Exception as e: 
        # PostgreSQL duplicate key error code is 23505, if the player already exists in the database, we can skip it and move on to the next one
        if "23505" in str(e):   
            #do nothing, the player already exists in the database
            pass    
        else:
            raise
    return player_ranked_stats_dict 


async def get_account_name_from_puuid(client: httpx.AsyncClient, puuid: str, region: str):
    get_summoner_data_url = f"https://{region}.api.riotgames.com/riot/account/v1/accounts/by-puuid/{puuid}"
    response = await riot_get_with_retry(client, url=get_summoner_data_url)
    return response.json()

async def get_player_league_data(client: httpx.AsyncClient, puuid: str, region: str):
    get_league_data_url = f"https://{region}.api.riotgames.com/tft/league/v1/by-puuid/{puuid}"
    response = await riot_get_with_retry(client, url=get_league_data_url)
    return response.json()

async def get_tiered_match_data(client: httpx.AsyncClient, tier: str, region: str):
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
            response = await riot_get(client, url=url, params=params)
            data = response.json()

            if not data:  # stop when no more players on this page
                break

            players.extend(data)  # append all players from this page
            page += 1       
    return players

async def populate_player_table_with_tiered_data(client: httpx.AsyncClient, region: str, db_client: Client):
    for player in await get_challengers(client, region=region):
        await prepare_player_data(client, puuid=player["puuid"], region=region, db_client=db_client)
    for player in await get_grandmasters(client, region=region):
        await prepare_player_data(client, puuid=player["puuid"], region=region, db_client=db_client)
    for player in await get_masters(client, region=region):
        await prepare_player_data(client, puuid=player["puuid"], region=region, db_client=db_client)
    

async def get_challenger_match_data(client: httpx.AsyncClient, region: str, db_client: Client) -> None:
    match_region_string = RIOT_REGIONS_MAP[region]

    # --- Phase 1: collect all unique new match IDs from every challenger ---
    challengers = await get_challengers(client, region=region)
    matches_in_db_response = (db_client.table("match").select("uuid").execute())
    matches_in_db = matches_in_db_response.data
    
    new_match_ids: list[str] = []
    for challenger in challengers:
        puuid = challenger["puuid"]
        print(f"Fetching match history for challenger (PUUID: {puuid}) in region {region}...")
        retrieval_start_time = get_unix_timestamp_from_n_days_ago(9)
        match_list = await get_match_history_from_last_n_days(client, puuid=puuid, startTime=retrieval_start_time, region=match_region_string)    
        if "status" in match_list:
            sys.exit(0)
        for match_id in match_list:
            if match_id not in matches_in_db and match_id not in new_match_ids:
                print('added match: ', match_id)
                new_match_ids.append(match_id)

    print(f"Collected {len(new_match_ids)} new match IDs. Fetching and uploading…")

    # --- Phase 2: fetch + upload concurrently, respecting Riot rate limits ---
    # Keep DB write pressure moderate to avoid transport resets from PostgREST.
    semaphore = asyncio.Semaphore(2)

    async def _fetch_and_upload(match_id: str) -> None:
        async with semaphore:
            match_data = await riot_get_with_retry(
                client,
                url=f"https://{match_region_string}.api.riotgames.com/tft/match/v1/matches/{match_id}",
            )
            parse_composition_data(
                match_data=match_data.json(), client=db_client
            )
            print(f"Uploaded {match_id}")

    await asyncio.gather(*[_fetch_and_upload(mid) for mid in new_match_ids])

def get_unix_timestamp_from_n_days_ago(n:int):
    date_today = date.today()
    target_date = date_today - timedelta(days=n)
    start_of_target_day_local = datetime.combine(target_date, datetime.min.time())
    unix_timestamp = time.mktime(start_of_target_day_local.timetuple())
    return int(unix_timestamp)

if __name__ == "__main__":
    _url: str = os.environ.get("supabase_url")
    _key: str = os.environ.get("supabase_key")
    _client: Client = create_client(_url, _key)

    async def _main() -> None:
        async with httpx.AsyncClient() as http_client:
            #await populate_player_table_with_tiered_data(http_client, region="SG2", db_client=_client)
            await get_challenger_match_data(http_client, "SG2", _client)

    asyncio.run(_main())