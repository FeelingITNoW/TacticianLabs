"""BigQuery helpers shared by the ingest job, the Airflow DAGs and the seed script.

Writes follow one pattern: load rows into fresh tables in the staging dataset
(load jobs are free, unlike streaming inserts or DML VALUES), then move them into
the real tables with a single SQL script. Table layouts come from the live tables,
which Terraform defines in infra/gcp/bigquery/.
"""

import os
import time
import uuid
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import TypeVar

from google.api_core import exceptions
from google.cloud import bigquery

DATASET = os.getenv("BQ_DATASET", "tft")
STAGING_DATASET = os.getenv("BQ_STAGING_DATASET", f"{DATASET}_staging")

T = TypeVar("T")

_schemas: dict[str, list[bigquery.SchemaField]] = {}


def make_client() -> bigquery.Client:
    # Application Default Credentials: the runner service account in Cloud Run, or
    # `gcloud auth application-default login` locally. GOOGLE_CLOUD_PROJECT picks
    # the project when the credentials don't imply one.
    return bigquery.Client(project=os.getenv("GOOGLE_CLOUD_PROJECT") or None)


def table_ref(client: bigquery.Client, name: str, dataset: str = DATASET) -> str:
    return f"{client.project}.{dataset}.{name}"


def table_schema(client: bigquery.Client, name: str) -> list[bigquery.SchemaField]:
    ref = table_ref(client, name)
    if ref not in _schemas:
        _schemas[ref] = client.get_table(ref).schema
    return _schemas[ref]


def column_names(client: bigquery.Client, name: str) -> list[str]:
    return [field.name for field in table_schema(client, name)]


def _is_retryable(exc: Exception) -> bool:
    if isinstance(
        exc,
        (
            exceptions.InternalServerError,
            exceptions.BadGateway,
            exceptions.ServiceUnavailable,
            exceptions.TooManyRequests,
        ),
    ):
        return True
    # Parallel Cloud Run tasks run DML against the same tables. When two collide,
    # BigQuery aborts one, and every script here is safe to rerun from the top.
    text = str(exc)
    return "concurrent update" in text or "Could not serialize access" in text


def with_retry(fn: Callable[[], T], max_retries: int = 6) -> T:
    delay = 1.0
    for attempt in range(max_retries):
        try:
            return fn()
        except Exception as exc:
            if attempt < max_retries - 1 and _is_retryable(exc):
                time.sleep(delay)
                delay = min(delay * 2, 32)
                continue
            raise
    raise RuntimeError("unreachable")


def run_query(
    client: bigquery.Client,
    sql: str,
    params: Sequence[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter] = (),
) -> list[bigquery.Row]:
    config = bigquery.QueryJobConfig(query_parameters=list(params))
    return with_retry(lambda: list(client.query(sql, job_config=config).result()))


def load_rows(
    client: bigquery.Client, name: str, rows: list[dict], destination: str
) -> str:
    """Load rows into a new table `destination`, shaped like table `name`."""
    config = bigquery.LoadJobConfig(schema=table_schema(client, name))
    with_retry(
        lambda: client.load_table_from_json(
            rows, destination, job_config=config
        ).result()
    )
    return destination


@contextmanager
def staged(
    client: bigquery.Client, rows_by_table: dict[str, list[dict]]
) -> Iterator[dict[str, str]]:
    """Stage each non-empty row list in its own staging table; yield name -> table id.

    A fresh table per call keeps the parallel Cloud Run tasks from clobbering each
    other. They are dropped on exit, and the staging dataset expires any a crash leaves.
    """
    staging: dict[str, str] = {}
    try:
        for name, rows in rows_by_table.items():
            if rows:
                staging[name] = load_rows(
                    client,
                    name,
                    rows,
                    destination=table_ref(
                        client, f"{name}_{uuid.uuid4().hex}", STAGING_DATASET
                    ),
                )
        yield staging
    finally:
        for staging_id in staging.values():
            client.delete_table(staging_id, not_found_ok=True)


def insert_from_staging_sql(client: bigquery.Client, name: str, staging_id: str) -> str:
    columns = ", ".join(column_names(client, name))
    return (
        f"INSERT INTO `{table_ref(client, name)}` ({columns})\n"
        f"SELECT {columns} FROM `{staging_id}`;"
    )
