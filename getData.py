from datetime import datetime
import json
import sys
import requests
import pandas as pd


# Store your Riot API key as an environment variable for security
RIOT_API_KEY = "RGAPI-3be20071-2c9f-4889-bc80-cbf0a23d0bd1"

HTTP_API_URL = "https://sea.api.riotgames.com/tft/match/v1/matches/SG2_101399858"
HTTP_GET_CHALLENGERS_API_URL = "https://sg2.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT"
HTTP_BASE_GET_ACCOUNT_URL = "https://asia.api.riotgames.com/riot/account/v1/accounts/by-puuid/"
HTTP_GET_GRANDMASTERS_API_URL = "https://sg2.api.riotgames.com/tft/league/v1/grandmaster?queue=RANKED_TFT"
HTTP_GET_MASTERS_API_URL = "https://sg2.api.riotgames.com/tft/league/v1/master?queue=RANKED_TFT"
SECONDS_IN_A_DAY = 86400

def get_match():
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url=HTTP_API_URL, headers=headers)
    response.raise_for_status()
    return response.json()

def get_match_history(puuid: str, start_index=0, end_index=20):
    headers = {"X-Riot-Token": RIOT_API_KEY}
    match_history_url = f"https://sea.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?start={start_index}&count={end_index}"
    response = requests.get(url=match_history_url, headers=headers)
    response.raise_for_status()
    return response.json()

def get_match_history_by_date(puuid: str, date: datetime, start_index=0, count=20):
    headers = {"X-Riot-Token": RIOT_API_KEY}
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

def get_challengers():
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url=HTTP_GET_CHALLENGERS_API_URL, headers=headers)
    response.raise_for_status()
    challengers = response.json()['entries']
    return challengers

def get_grandmasters():
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url=HTTP_GET_GRANDMASTERS_API_URL, headers=headers)
    response.raise_for_status()
    grandmasters = response.json()['entries']
    return grandmasters

def get_masters():
    headers = {"X-Riot-Token": RIOT_API_KEY}
    response = requests.get(url=HTTP_GET_MASTERS_API_URL, headers=headers)
    response.raise_for_status()
    masters = response.json()['entries']
    return masters

def is_new_match(match: str, recorded_matches: list):
    return match in recorded_matches

def get_match_data(match_id: str):
    headers = {"X-Riot-Token": RIOT_API_KEY}
    get_match_data_url = f"https://sea.api.riotgames.com/tft/match/v1/matches/{match_id}"
    response = requests.get(url=get_match_data_url, headers=headers)
    response.raise_for_status()
    
    return response.json()

def parse_match_data(match_data: dict, match_id: str):
    participants = match_data["info"]["participants"]
    match_dataframe = pd.DataFrame(participants)
    for _, row in match_dataframe.iterrows():
        create_composition(match_data_row=row, match_id=match_id)
    
def create_composition(match_data_row: dict, match_id: str):
    composition_dict = dict()
    composition_dict["info"] = dict()
    composition_dict['info']['match_id'] = match_id
    composition_dict['info']['placement'] = match_data_row["placement"]
    units = []
    for unit in match_data_row['units']:
        units.append(unit)
    composition_dict['units'] = units
    normalized = pd.json_normalize(composition_dict)
    composition_dataframe = pd.DataFrame(normalized)
    composition_dataframe.to_csv(f"files/composition/{match_id}_{match_data_row['puuid']}.csv", index=False)
    return composition_dict


if __name__ == "__main__":
    challengers = get_challengers()
    for day in range(12, 17):
        dt = datetime(2025, 10, day, 0, 0)
        for challenger in challengers:
            puuid = challenger['puuid']
            match_history_by_date = get_match_history_by_date(puuid=puuid, count=100, date=dt)
            with open("matches_queued.txt", "r") as queue_file_reader:
                match_list = queue_file_reader.read().split("\n")
            with open("matches_queued.txt", "a") as queue_file_writer:
                for match_id in match_history_by_date:
                    if match_id == "status":
                        sys.exit(0)

                    if match_id in match_list:
                        print(f"skipped {match_id}")
                        continue
                    
                    match_list.append(match_id)  
                    print(f"added {match_id}")
                    queue_file_writer.write(match_id + "\n")
        print(f"done with Oct {day}")

        
    