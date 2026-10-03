import json
from datetime import datetime, timezone

from google import genai
from google.cloud import bigquery

from db.bq import insert_from_staging_sql, run_query, staged, table_ref
from db.upsert_players import merge_players_sql
from google_embedding.embedding_call import Unit, get_embeddings
from riot_api.constants import TFT_RANKED_QUEUE_ID

# Per-match tables, children first. write_match_rows replaces a match's rows in
# all of them, and matches itself is handled separately (out first, in last).
MATCH_CHILD_TABLES = (
    "unit_items",
    "participant_units",
    "participant_traits",
    "participants",
)


def build_match_rows(
    match_data: dict,
    latest_version: str,
    google_genai_client: genai.Client | None,
) -> dict[str, list[dict]] | None:
    """Turn one Riot match payload into rows keyed by BigQuery table name.

    Returns None for anything that isn't a ranked game. Calls Gemini once to embed
    every participant's board (units with star level and items, plus traits), or not at all when google_genai_client is None, in
    which case the participant rows have no embedding.
    """
    info = match_data["info"]
    match_id = match_data["metadata"]["match_id"]
    if info["queue_id"] != TFT_RANKED_QUEUE_ID:
        print(
            f"Skipping match {match_id} - not a ranked game (queue_id: {info['queue_id']})"
        )
        return None

    # Match IDs are prefixed with the platform, e.g. "NA1_5123456789"
    platform = match_id.split("_")[0]
    # Riot sends epoch milliseconds. Every per-match table is partitioned on this.
    played_at = datetime.fromtimestamp(
        info["game_datetime"] / 1000, tz=timezone.utc
    ).isoformat()

    player_rows: list[dict] = []
    participant_rows: list[dict] = []
    trait_rows: dict[tuple, dict] = {}
    unit_rows: list[dict] = []
    unit_item_rows: list[dict] = []
    compositions: list[tuple[list[Unit], list[str]]] = []
    for participant in info["participants"]:
        puuid = participant["puuid"]
        keys = {"match_id": match_id, "puuid": puuid, "played_at": played_at}
        # Lobbies include players outside the tiers we crawl, so every participant
        # gets a players row (participants.puuid references players).
        player_rows.append(
            {
                "puuid": puuid,
                "game_name": participant.get("riotIdGameName"),
                "tag_line": participant.get("riotIdTagline"),
                "region": platform,
            }
        )
        participant_rows.append(
            {
                **keys,
                "placement": participant["placement"],
                "level": participant["level"],
                "gold_left": participant["gold_left"],
                "last_round": participant["last_round"],
                "total_damage_to_players": participant["total_damage_to_players"],
            }
        )

        for trait in participant["traits"]:
            # Keyed on the primary key, which BigQuery records but doesn't enforce
            trait_rows[(puuid, trait["name"])] = {
                **keys,
                "trait": trait["name"],
                "num_units": trait["num_units"],
                "style": trait["style"],
                "tier_current": trait["tier_current"],
                "tier_total": trait["tier_total"],
            }

        # slot is the unit's position on the board list, so two copies of the same
        # champion stay separate rows.
        for slot, unit in enumerate(participant["units"]):
            unit_rows.append(
                {
                    **keys,
                    "slot": slot,
                    "champion": unit["character_id"],
                    "star": unit["tier"],
                    "rarity": unit["rarity"],
                }
            )
            for item_index, item in enumerate(unit.get("itemNames", [])):
                unit_item_rows.append(
                    {**keys, "slot": slot, "item_index": item_index, "item": item}
                )

        compositions.append(
            (
                [
                    (unit["character_id"], unit["tier"], unit.get("itemNames", []))
                    for unit in participant["units"]
                ],
                [trait["name"] for trait in participant["traits"]],
            )
        )

    # One embedding request per match instead of one per participant
    if participant_rows and google_genai_client is not None:
        embeddings = get_embeddings(google_genai_client, compositions)
        for row, embedding in zip(participant_rows, embeddings):
            row["embedding"] = embedding

    return {
        "matches": [
            {
                "match_id": match_id,
                "played_at": played_at,
                "game_length": info.get("game_length"),
                "game_version": latest_version,
                "tft_set_number": info.get("tft_set_number"),
                "queue_id": info["queue_id"],
                "region": platform,
            }
        ],
        "players": player_rows,
        "participants": participant_rows,
        "participant_traits": list(trait_rows.values()),
        "participant_units": unit_rows,
        "unit_items": unit_item_rows,
    }


def write_match_rows(
    client: bigquery.Client, batches: list[dict[str, list[dict]]]
) -> None:
    """Replace the given matches' rows in every per-match table and upsert players.

    Idempotent, since the daily look-back windows overlap and a failed run is
    retried. The matches row is deleted first and inserted last, so a run that
    dies part-way leaves the match absent and filter_new_match_ids re-ingests it.
    """
    if not batches:
        return
    rows = {name: [row for batch in batches for row in batch[name]] for name in batches[0]}
    match_ids = [row["match_id"] for row in rows["matches"]]
    played = [datetime.fromisoformat(row["played_at"]) for row in rows["matches"]]
    params = [
        bigquery.ArrayQueryParameter("match_ids", "STRING", match_ids),
        # Bounds the deletes to the partitions these matches live in
        bigquery.ScalarQueryParameter("lo", "TIMESTAMP", min(played)),
        bigquery.ScalarQueryParameter("hi", "TIMESTAMP", max(played)),
    ]

    def delete_sql(name: str) -> str:
        return (
            f"DELETE FROM `{table_ref(client, name)}`\n"
            "WHERE match_id IN UNNEST(@match_ids) AND played_at BETWEEN @lo AND @hi;"
        )

    with staged(client, rows) as staging:
        statements = [delete_sql("matches")]
        for name in MATCH_CHILD_TABLES:
            statements.append(delete_sql(name))
            if name in staging:
                statements.append(insert_from_staging_sql(client, name, staging[name]))
        statements.append(merge_players_sql(client, staging["players"]))
        statements.append(insert_from_staging_sql(client, "matches", staging["matches"]))
        run_query(client, "\n".join(statements), params)


def write_matches(
    client: bigquery.Client,
    match_bodies: dict[str, str],
    latest_version: str,
    google_genai_client: genai.Client | None,
) -> tuple[int, int]:
    """Parse raw match JSON (match_id -> body) and write the batch in one round.

    Returns (ingested, failed). A match that fails to parse is skipped and counted.
    A failed write raises for the whole batch, which is safe to retry.
    """
    batches: list[dict[str, list[dict]]] = []
    failed = 0
    for match_id, body in match_bodies.items():
        try:
            rows = build_match_rows(json.loads(body), latest_version, google_genai_client)
        except Exception as exc:
            failed += 1
            print(f"Failed to parse {match_id}: {exc!r}")
            continue
        if rows is not None:
            batches.append(rows)
    write_match_rows(client, batches)
    return len(batches), failed


def filter_new_match_ids(client: bigquery.Client, match_ids: list[str]) -> list[str]:
    """Drop match IDs that are already in the matches table."""
    if not match_ids:
        return []
    rows = run_query(
        client,
        f"SELECT match_id FROM `{table_ref(client, 'matches')}` "
        "WHERE match_id IN UNNEST(@match_ids)",
        [bigquery.ArrayQueryParameter("match_ids", "STRING", match_ids)],
    )
    existing = {row["match_id"] for row in rows}
    return [match_id for match_id in match_ids if match_id not in existing]
