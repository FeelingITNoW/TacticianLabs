import json
from datetime import datetime, timezone

from google import genai
from google.cloud import bigquery

from data_aggregation.data_aggregation import merge_totals_sql
from db.bq import column_names, insert_from_staging_sql, run_query, staged, table_ref
from db.upsert_players import merge_players_sql
from google_embedding.embedding_call import Unit, get_embeddings
from riot_api.constants import (
    RANKED_QUEUES,
    TFT_NORMAL_QUEUE_ID,
    allowed_queues,
)

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
    queues: frozenset[int] = RANKED_QUEUES,
) -> dict[str, list[dict]] | None:
    """Turn one Riot match payload into rows keyed by BigQuery table name.

    Returns None for a game whose queue isn't in `queues` (ranked only by default). Calls Gemini once to embed
    every participant's board (units with star level and items, plus traits), or not at all when google_genai_client is None, in
    which case the participant rows have no embedding.
    """
    info = match_data["info"]
    match_id = match_data["metadata"]["match_id"]
    if info["queue_id"] not in queues:
        print(
            f"Skipping match {match_id} - queue {info['queue_id']} isn't one of {sorted(queues)}"
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
    """Replace the given matches' rows in every per-match table, upsert players and
    fold the matches into the per-patch totals.

    Idempotent, since the daily look-back windows overlap and a failed run is
    retried. The whole script is one transaction, so the totals can't be bumped
    without the matches landing (which would double count on the retry). The
    totals come first because they subtract the rows the deletes then remove.
    The matches row is deleted first and inserted last among the writes.
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
        statements = [*merge_totals_sql(client, staging), delete_sql("matches")]
        for name in MATCH_CHILD_TABLES:
            statements.append(delete_sql(name))
            if name in staging:
                statements.append(insert_from_staging_sql(client, name, staging[name]))
        statements.append(merge_players_sql(client, staging["players"]))
        statements.append(insert_from_staging_sql(client, "matches", staging["matches"]))
        script = "\n".join(["BEGIN TRANSACTION;", *statements, "COMMIT TRANSACTION;"])
        run_query(client, script, params)


def write_matches(
    client: bigquery.Client,
    match_bodies: dict[str, str],
    latest_version: str,
    google_genai_client: genai.Client | None,
    queues: frozenset[int] = RANKED_QUEUES,
) -> tuple[int, int]:
    """Parse raw match JSON (match_id -> body) and write the batch in one round.

    Games outside `queues` are skipped. Returns (ingested, failed). A match that
    fails to parse is skipped and counted.
    A failed write raises for the whole batch, which is safe to retry.
    """
    batches: list[dict[str, list[dict]]] = []
    failed = 0
    for match_id, body in match_bodies.items():
        try:
            rows = build_match_rows(
                json.loads(body), latest_version, google_genai_client, queues
            )
        except Exception as exc:
            failed += 1
            print(f"Failed to parse {match_id}: {exc!r}")
            continue
        if rows is not None:
            batches.append(rows)
    write_match_rows(client, batches)
    return len(batches), failed


def select_matches(
    match_bodies: dict[str, str], sources: dict[str, list[str]]
) -> tuple[dict[str, str], list[dict]]:
    """Split fetched matches (match_id -> body) into the ones to record and the rejected.

    A match is recorded when its queue is allowed for the tiers whose players had it
    (`sources`, from collect_match_ids): ranked from any tier, normals only from a
    Challenger. Rejected ones come back as `rejected_matches` rows, so later runs
    skip them instead of fetching them again. A body that can't be read is kept, so
    write_matches counts it as a failure and it is retried tomorrow.
    """
    accepted: dict[str, str] = {}
    rejected: list[dict] = []
    for match_id, body in match_bodies.items():
        try:
            info = json.loads(body)["info"]
            queue_id = info["queue_id"]
            played_at = datetime.fromtimestamp(
                info["game_datetime"] / 1000, tz=timezone.utc
            ).isoformat()
        except Exception:
            accepted[match_id] = body
            continue
        if queue_id in allowed_queues(sources.get(match_id, ())):
            accepted[match_id] = body
            continue
        reason = "normal_not_challenger" if queue_id == TFT_NORMAL_QUEUE_ID else "queue"
        rejected.append(
            {
                "match_id": match_id,
                "played_at": played_at,
                "queue_id": queue_id,
                "reason": reason,
                "rejected_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    return accepted, rejected


def write_rejected_matches(client: bigquery.Client, rows: list[dict]) -> None:
    """Remember rejected matches so filter_new_match_ids skips them. Safe to repeat."""
    if not rows:
        return
    with staged(client, {"rejected_matches": rows}) as staging:
        columns = ", ".join(column_names(client, "rejected_matches"))
        values = ", ".join(f"s.{c}" for c in column_names(client, "rejected_matches"))
        run_query(
            client,
            f"MERGE `{table_ref(client, 'rejected_matches')}` AS t\n"
            f"USING `{staging['rejected_matches']}` AS s ON t.match_id = s.match_id\n"
            f"WHEN NOT MATCHED THEN INSERT ({columns}) VALUES ({values});",
        )


def filter_new_match_ids(client: bigquery.Client, match_ids: list[str]) -> list[str]:
    """Drop match IDs that are already in the matches table or were rejected before."""
    if not match_ids:
        return []
    rows = run_query(
        client,
        f"SELECT match_id FROM `{table_ref(client, 'matches')}` "
        "WHERE match_id IN UNNEST(@match_ids)\n"
        "UNION ALL\n"
        f"SELECT match_id FROM `{table_ref(client, 'rejected_matches')}` "
        "WHERE match_id IN UNNEST(@match_ids)",
        [bigquery.ArrayQueryParameter("match_ids", "STRING", match_ids)],
    )
    existing = {row["match_id"] for row in rows}
    return [match_id for match_id in match_ids if match_id not in existing]
