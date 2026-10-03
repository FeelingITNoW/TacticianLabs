import httpx
from google.cloud import bigquery

from db.bq import run_query, staged, table_ref
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


def merge_players_sql(client: bigquery.Client, staging_id: str) -> str:
    """Upsert staged players. A NULL name or region never overwrites a known one,
    because league rows carry no names and match rows do."""
    return f"""
MERGE `{table_ref(client, "players")}` AS t
USING (
  SELECT puuid, ANY_VALUE(game_name) AS game_name, ANY_VALUE(tag_line) AS tag_line,
         ANY_VALUE(region) AS region
  FROM `{staging_id}`
  GROUP BY puuid
) AS s
ON t.puuid = s.puuid
WHEN MATCHED THEN UPDATE SET
  game_name = COALESCE(s.game_name, t.game_name),
  tag_line = COALESCE(s.tag_line, t.tag_line),
  region = COALESCE(s.region, t.region),
  updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (puuid, game_name, tag_line, region, created_at, updated_at)
  VALUES (s.puuid, s.game_name, s.tag_line, s.region, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP());
"""


def merge_ranked_stats_sql(client: bigquery.Client, staging_id: str) -> str:
    return f"""
MERGE `{table_ref(client, "player_ranked_stats")}` AS t
USING (
  SELECT * FROM `{staging_id}`
  WHERE TRUE
  QUALIFY ROW_NUMBER() OVER (PARTITION BY puuid ORDER BY league_points DESC) = 1
) AS s
ON t.puuid = s.puuid
WHEN MATCHED THEN UPDATE SET
  tier = s.tier, `rank` = s.`rank`, league_points = s.league_points, wins = s.wins,
  losses = s.losses, hot_streak = s.hot_streak, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN
  INSERT (puuid, tier, `rank`, league_points, wins, losses, hot_streak, updated_at)
  VALUES (s.puuid, s.tier, s.`rank`, s.league_points, s.wins, s.losses, s.hot_streak,
          CURRENT_TIMESTAMP());
"""


async def upsert_high_elo_players(
    client: httpx.AsyncClient,
    region: str,
    db_client: bigquery.Client,
    tiers: list[str] = HIGH_ELO_TIERS,
) -> int:
    """Upsert players + ranked stats for the given apex tiers on one platform.

    Returns the number of players written.
    """
    players: list[dict] = []
    ranked_stats: list[dict] = []
    for tier in tiers:
        league = await get_league_entries(client, region, tier)
        tier_players, tier_stats = build_player_rows(league, region)
        print(f"Fetched {len(tier_players)} {tier} players for {region}")
        players.extend(tier_players)
        ranked_stats.extend(tier_stats)
    if not players:
        return 0

    # All tiers share one staging round: two load jobs and one query per platform
    with staged(
        db_client, {"players": players, "player_ranked_stats": ranked_stats}
    ) as staging:
        run_query(
            db_client,
            merge_players_sql(db_client, staging["players"])
            + merge_ranked_stats_sql(db_client, staging["player_ranked_stats"]),
        )
    print(f"Upserted {len(players)} players for {region}")
    return len(players)
