from datetime import datetime
import asyncio
import json
import sys
import requests
import os
from dotenv import load_dotenv

load_dotenv()

RIOT_API_KEY = os.getenv('API_KEY')
SECONDS_IN_A_DAY = 86400
LOCAL_STORAGE_DIRECTORY = "../files/match"
API_HEADER = {"X-Riot-Token": RIOT_API_KEY}
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


def get_match_history(puuid: str, region: str, start_index=0, end_index=20):
    headers = API_HEADER
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?start={start_index}&count={end_index}"
    response = requests.get(url=match_history_url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_match_history_by_date(puuid: str, date: datetime, start_index=0, count=20):
    headers = API_HEADER
    epoch_seconds_start = int(date.timestamp())
    epoch_seconds_end = epoch_seconds_start + SECONDS_IN_A_DAY
    match_history_url = f"https://sea.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {
        "startTime": epoch_seconds_start,
        "endTime": epoch_seconds_end,
        "count": count
    }
    response = requests.get(url=match_history_url, params=params, headers=headers)
    return response.json()

def get_last_100_matches(puuid: str, region: str):
    headers = API_HEADER
    match_history_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {
        "count": 100
    }
    response = requests.get(url=match_history_url, params=params, headers=headers)
    return response.json()
    
def get_challengers(region: str):
    headers = API_HEADER
    HTTP_GET_CHALLENGERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT"
    response = requests.get(url=HTTP_GET_CHALLENGERS_API_URL, headers=headers)
    response.raise_for_status()
    challengers = response.json()['entries']
    return challengers

def get_grandmasters(region: str):
    headers = API_HEADER
    HTTP_GET_GRANDMASTERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/grandmaster?queue=RANKED_TFT"
    response = requests.get(url=HTTP_GET_GRANDMASTERS_API_URL, headers=headers)
    response.raise_for_status()
    grandmasters = response.json()['entries']
    return grandmasters

def get_masters(region: str):
    headers = API_HEADER
    HTTP_GET_MASTERS_API_URL = f"https://{region}.api.riotgames.com/tft/league/v1/master?queue=RANKED_TFT"
    response = requests.get(url=HTTP_GET_MASTERS_API_URL, headers=headers)
    response.raise_for_status()
    masters = response.json()['entries']
    return masters

async def get_all_players_below_masters(region: str, tier=None, division=None):
    headers = API_HEADER
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
                
                response = requests.get(url, headers=headers, params=params)
                response.raise_for_status()
                data = response.json()

                if not data:  # stop when no more players on this page
                    break

                players.extend(data)  # append all players from this page
                page += 1       
                print(f"page {page}")
            print(f"done with {tier} {division}")
    return players

def is_new_match(match: str, recorded_matches: list):
    return match in recorded_matches

def get_match_data(match_id: str, region: str):
    headers = API_HEADER
    get_match_data_url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/{match_id}"
    response = requests.get(url=get_match_data_url, headers=headers)
    response.raise_for_status()

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
            response = requests.get(url, headers=API_HEADER, params=params)
            response.raise_for_status()
            data = response.json()

            if not data:  # stop when no more players on this page
                break

            players.extend(data)  # append all players from this page
            page += 1       
    return players

async def get_challenger_match_data(region: str):
    challengers = get_challengers(region=region)
    match_region_string = RIOT_REGIONS_MAP[region]
    for challenger in challengers:
        puuid = challenger['puuid']
        await asyncio.sleep(2)
        last_100_matches = get_last_100_matches(region=match_region_string, puuid=puuid)
        with open("matches_queued.txt", "r") as queue_file_reader:
            match_list = queue_file_reader.read().split("\n")
        with open("matches_queued.txt", "a") as queue_file_writer:
            for match_id in last_100_matches:
                if match_id == "status":
                    sys.exit(0)

                if match_id in match_list:
                    continue
                
                #wait 2 seconds to prevent reaching request limit
                await asyncio.sleep(2)
                match_list.append(match_id)  
                with open(f"../files/match/{match_id}.json", "w") as f:
                    json.dump(get_match_data(region=match_region_string, match_id=match_id), f, indent=4)
                queue_file_writer.write(match_id + "\n")



if __name__ == "__main__":
    #asyncio.run(get_challenger_match_data("euw1"))
    print(asyncio.run(get_all_players_below_masters("euw1")))