from datetime import datetime

from airflow.sdk import dag, task  # type: ignore
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook  # type: ignore

from data_aggregation.data_aggregation import rebuild_totals


# The ingest writes keep the *_totals tables current, so this has no schedule. Trigger
# it by hand to backfill after creating the tables, or to recover from a bad write
# (python -m jobs.rebuild_stats --check reports whether that is needed).
@dag(
    dag_id="calculate_tft_stats",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["stats"],
)
def calculate_tft_stats():

    @task
    def rebuild_totals_task() -> None:
        # Same connection and service account as the ingest DAG
        client = BigQueryHook(gcp_conn_id="google_cloud_default").get_client()
        rebuild_totals(client)
        print("Rebuilt every totals table")

    rebuild_totals_task()


calculate_tft_stats()
