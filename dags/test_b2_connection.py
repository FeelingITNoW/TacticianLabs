from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from datetime import datetime

def list_b2_buckets():
    hook = S3Hook(aws_conn_id='backblaze_b2')

    # The ingest key is bucket-scoped, so ListBuckets is not permitted.
    # Use list_objects_v2 against the specific bucket instead.
    client = hook.get_conn()
    response = client.list_objects_v2(Bucket='tft-match-data', MaxKeys=20)

    objects = response.get('Contents', [])
    if not objects:
        print("Bucket is empty (connection OK)")
    for obj in objects:
        print(f"Key: {obj['Key']}  Size: {obj['Size']}")

with DAG(
    dag_id='test_backblaze_connection',
    start_date=datetime(2026, 1, 1),
    schedule=None,
    catchup=False
) as dag:

    test_task = PythonOperator(
        task_id='list_buckets_task',
        python_callable=list_b2_buckets
    )