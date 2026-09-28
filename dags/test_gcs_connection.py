from airflow import DAG  # type: ignore
from airflow.providers.standard.operators.python import PythonOperator  # type: ignore
from airflow.providers.google.cloud.hooks.gcs import GCSHook  # type: ignore
from datetime import datetime


def list_gcs_objects():
    hook = GCSHook(gcp_conn_id="google_cloud_default")
    objects = hook.list(bucket_name="tft-match-data", max_results=20)

    if not objects:
        print("Bucket is empty (connection OK)")
    for name in objects:
        print(f"Object: {name}")


with DAG(
    dag_id="test_gcs_connection",
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False,
    tags=["test"],
    default_args={"owner": "Astro", "retries": 3},
) as dag:
    test_task = PythonOperator(
        task_id="list_objects_task", python_callable=list_gcs_objects
    )
