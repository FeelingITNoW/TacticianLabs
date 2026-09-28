import httpx
from supabase import Client

from db.parse_match_data import _execute_with_retry
from riot_api.constants import HIGH_ELO_TIERS
from riot_api.league_api import get_league_entries


def build_player_rows(league: dict, region: str) -> tuple[list[dict], list[dict]]:
    """Turn a league list response into players and player_ranked_stats rows.

    The league list already carries everything player_ranked_stats needs, so no
    per-player Riot calls are required. Names come from match payloads instead.
    """
    tier = league.get("tier")
    players: list[dict] = []
    ranked_stats: list[dict] = []
    for entry in league.get("entries", []):
        players.append({"puuid": entry["puuid"], "region": region})
        ranked_stats.append(
            {
                "puuid": entry["puuid"],
                "tier": tier,
                "rank": entry.get("rank"),
                "league_points": entry.get("leaguePoints", 0),
                "wins": entry.get("wins", 0),
                "losses": entry.get("losses", 0),
                "hot_streak": entry.get("hotStreak", False),
            }
        )
    return players, ranked_stats


async def upsert_high_elo_players(
    client: httpx.AsyncClient,
    region: str,
    db_client: Client,
    tiers: list[str] = HIGH_ELO_TIERS,
) -> int:
    """Upsert players + ranked stats for the given apex tiers on one platform.

    Returns the number of players written.
    """
    total = 0
    for tier in tiers:
        league = await get_league_entries(client, region, tier)
        players, ranked_stats = build_player_rows(league, region)
        if not players:
            continue
        # players first: player_ranked_stats.puuid references it
        _execute_with_retry(
            db_client.table("players").upsert(players, on_conflict="puuid")
        )
        _execute_with_retry(
            db_client.table("player_ranked_stats").upsert(
                ranked_stats, on_conflict="puuid"
            )
        )
        print(f"Upserted {len(players)} {tier} players for {region}")
        total += len(players)
    return total
