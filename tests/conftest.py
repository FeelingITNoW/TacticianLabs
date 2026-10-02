import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

# Use an in-memory SQLite DB for Airflow's metadata — must be set before any Airflow import
os.environ.setdefault(
    "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", "sqlite:////tmp/airflow_test.db"
)
os.environ.setdefault("AIRFLOW__CORE__EXECUTOR", "LocalExecutor")
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
# Bypass Airflow's custom structlog formatter which causes a circular import
# when airflow.utils is referenced before the airflow module is fully initialized
os.environ.setdefault("AIRFLOW__LOGGING__LOGGING_CONFIG_CLASS", "")

# The Terraform table definitions, so fakes and the real tables can't drift apart
BIGQUERY_SCHEMA_DIR = Path(__file__).parent.parent / "infra" / "gcp" / "bigquery"


@pytest.fixture(scope="session", autouse=True)
def initialize_airflow_db():
    from airflow.utils import db

    db.initdb()


class FakeBigQuery:
    """Stands in for google.cloud.bigquery.Client.

    Table schemas come from infra/gcp/bigquery/*.json. Loads and queries are
    recorded instead of run, and every loaded row is checked against its table's
    schema: unknown columns and missing REQUIRED columns fail the test.
    """

    project = "test-project"

    def __init__(self, query_rows: list[dict] | None = None):
        self.query_rows = query_rows or []
        self.loads: dict[str, list[dict]] = {}
        self.queries: list[tuple[str, list]] = []
        self.deleted: list[str] = []

    @staticmethod
    def _fields(table_ref: str) -> list[dict]:
        name = table_ref.rsplit(".", 1)[1]
        return json.loads((BIGQUERY_SCHEMA_DIR / f"{name}.json").read_text())

    def get_table(self, table_ref: str):
        from google.cloud import bigquery

        return SimpleNamespace(
            schema=[
                bigquery.SchemaField(f["name"], f["type"], mode=f.get("mode", "NULLABLE"))
                for f in self._fields(table_ref)
            ]
        )

    def load_table_from_json(self, rows, destination, job_config):
        rows = list(rows)
        fields = {f.name: f for f in job_config.schema}
        required = {name for name, f in fields.items() if f.mode == "REQUIRED"}
        for row in rows:
            assert set(row) <= set(fields), f"{destination}: unknown {set(row) - set(fields)}"
            assert required <= set(row), f"{destination}: missing {required - set(row)}"
        self.loads[destination] = rows
        return SimpleNamespace(result=lambda: None)

    def query(self, sql, job_config=None):
        params = list(job_config.query_parameters) if job_config else []
        self.queries.append((sql, params))
        return SimpleNamespace(result=lambda: self.query_rows)

    def delete_table(self, table_ref, not_found_ok=False):
        self.deleted.append(table_ref)

    def staged(self, name: str) -> list[dict]:
        """Rows loaded into staging tables for table `name`."""
        return [
            row
            for destination, rows in self.loads.items()
            if destination.rsplit(".", 1)[1].rsplit("_", 1)[0] == name
            for row in rows
        ]


@pytest.fixture
def fake_bq() -> FakeBigQuery:
    return FakeBigQuery()
