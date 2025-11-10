import pandas as pd 

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