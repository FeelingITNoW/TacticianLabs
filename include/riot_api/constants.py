import os

RIOT_API_KEY = os.getenv("RIOT_API_KEY") or os.getenv("API_KEY")
RIOT_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
SECONDS_IN_A_DAY = 86400
RANK_TIERS = [
    "IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM",
    "EMERALD", "DIAMOND", "MASTER", "GRANDMASTER", "CHALLENGER",
]
RANK_DIVISIONS = ["I", "II", "III", "IV"]
RIOT_REGIONS = [
    "BR1", "EUN1", "EUW1", "JP1", "KR",
    "LA1", "LA2", "NA1", "OC1",
    "PH2", "SG2", "TH2", "TW2", "VN2",
]

# Platform → routing-region mapping
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
    # Southeast Asia
    "PH2": "SEA",
    "SG2": "SEA",
    "TH2": "SEA",
    "TW2": "SEA",
    "VN2": "SEA",
}
