from datetime import datetime

from airflow.sdk import dag, task  # type: ignore
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook  # type: ignore

from data_aggregation.data_aggregation import STATS_SOURCES, refresh_stats


@dag(
    dag_id="calculate_tft_stats",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["stats"],
)
def calculate_tft_stats():

    @task
    def refresh_stats_task(stats_table: str) -> None:
        # Same connection and service account as the ingest DAG
        client = BigQueryHook(gcp_conn_id="google_cloud_default").get_client()
        refresh_stats(client, stats_table)
        print(f"Rebuilt {stats_table}")

    refresh_stats_task.expand(stats_table=list(STATS_SOURCES))


calculate_tft_stats()
