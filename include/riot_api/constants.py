import os

RIOT_API_KEY = os.getenv("RIOT_API_KEY") or os.getenv("API_KEY")
RIOT_VERSIONS_URL = "https://ddragon.leagueoflegends.com/api/versions.json"
SECONDS_IN_A_DAY = 86400
VALID_RANK_TIERS = [
    "IRON",
    "BRONZE",
    "SILVER",
    "GOLD",
    "PLATINUM",
    "EMERALD",
    "DIAMOND",
    "MASTER",
    "GRANDMASTER",
    "CHALLENGER",
]
# The apex tiers the ingest crawls, in priority order. Every Challenger and Grandmaster on
# a routing region's platforms is always crawled. Masters (~28k across RIOT_REGIONS, one
# match-history request each) only fill what is left of ROUTING_MATCH_TARGET new matches
# per routing region, round-robin by LP rank across the platforms. Every Master still
# gets a players row, since the league list is one request.
HIGH_ELO_TIERS = ["CHALLENGER", "GRANDMASTER", "MASTER"]
ROUTING_MATCH_TARGET = 2000
# Masters crawled between checks of how many new matches the routing region has
MASTER_CRAWL_BATCH = 20
LOW_ELO_TIERS = ["IRON", "BRONZE", "SILVER", "GOLD", "PLATINUM", "EMERALD", "DIAMOND"]
TFT_RANKED_QUEUE_ID = 1100
TFT_NORMAL_QUEUE_ID = 1090
RANKED_QUEUES = frozenset({TFT_RANKED_QUEUE_ID})
# Queues recorded when a player of the tier had the match in their history. Ranked from
# any tier, normals only from Challengers; every other mode (Hyper Roll, Double Up, ...)
# is rejected. A match several tiers surfaced is judged by the union of their queues.
TIER_QUEUES = {
    "CHALLENGER": frozenset({TFT_RANKED_QUEUE_ID, TFT_NORMAL_QUEUE_ID}),
    "GRANDMASTER": RANKED_QUEUES,
    "MASTER": RANKED_QUEUES,
}
# Everything any tier may record; what the DB writers accept
INGEST_QUEUES = frozenset().union(*TIER_QUEUES.values())


def allowed_queues(tiers) -> frozenset[int]:
    """Queues worth recording for a match the given tiers' players had. With no tier
    information, only ranked."""
    allowed = frozenset().union(*(TIER_QUEUES.get(tier, frozenset()) for tier in tiers))
    return allowed or RANKED_QUEUES


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
    "SG2",
    "TW2",
    "VN2",
]
# RIOT_REGIONS = ["SG2"]
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
    "OC1": "SEA",
    "SG2": "SEA",
    "TW2": "SEA",
    "VN2": "SEA",
}


def routing_groups() -> dict[str, list[str]]:
    """Platforms in RIOT_REGIONS grouped by routing region, in a stable order."""
    groups: dict[str, list[str]] = {}
    for platform in RIOT_REGIONS:
        groups.setdefault(RIOT_REGIONS_MAP[platform], []).append(platform)
    return dict(sorted(groups.items()))
