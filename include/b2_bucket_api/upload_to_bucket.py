

from datetime import UTC, datetime


async def upload_matches(
    match_data: dict[str, str],
    s3_client,
    bucket_name: str,
    riot_version: str
) -> None:
    utc_now = datetime.now(UTC)
    utc_date = utc_now.date()
    print(f"Uploading {len(match_data)} matches to {bucket_name} under version {riot_version}…")
    for match_id, body in match_data.items():
        s3_client.put_object(
            Bucket=bucket_name,
            Key=f"tft/matches/{riot_version}/{utc_date}/{match_id}.json",
            Body=body,
            ContentType="application/json",
        )
        print(f"Uploaded {match_id}")
