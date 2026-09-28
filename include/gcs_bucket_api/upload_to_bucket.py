from datetime import UTC, datetime


async def upload_matches(
    match_data: dict[str, str],
    storage_client,
    bucket_name: str,
    riot_version: str,
) -> None:
    utc_now = datetime.now(UTC)
    utc_date = utc_now.date()
    bucket = storage_client.bucket(bucket_name)
    print(
        f"Uploading {len(match_data)} matches to {bucket_name} under version {riot_version}…"
    )
    for match_id, body in match_data.items():
        blob = bucket.blob(f"tft/matches/{riot_version}/{utc_date}/{match_id}.json")
        blob.upload_from_string(body, content_type="application/json")
        print(f"Uploaded {match_id}")
