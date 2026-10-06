from datetime import datetime

from airflow.sdk import dag, task  # type: ignore
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook  # type: ignore

from data_aggregation.compositions import cluster_patch, latest_patch


# Production runs this as the tft-cluster-compositions Cloud Run Job (see
# include/jobs/cluster_compositions.py). This DAG is for local runs, so it has no schedule.
@dag(
    dag_id="cluster_compositions",
    schedule=None,
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["stats"],
)
def cluster_compositions():

    @task
    def cluster_latest_patch_task() -> None:
        # Same connection and service account as the ingest DAG
        client = BigQueryHook(gcp_conn_id="google_cloud_default").get_client()
        patch = latest_patch(client)
        if patch is None:
            raise ValueError("No patches yet: ingest some matches first")
        cluster_patch(client, patch)

    cluster_latest_patch_task()


cluster_compositions()
