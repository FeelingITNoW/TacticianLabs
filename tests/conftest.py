import os
import pytest
from supabase import create_client, Client

LOCAL_SUPABASE_URL = os.getenv(
    "LOCAL_SUPABASE_URL", "http://host.docker.internal:54321"
)
# Use the service_role (secret) key so tests bypass RLS and can read all rows
LOCAL_SUPABASE_KEY = os.getenv(
    "LOCAL_SUPABASE_KEY", "sb_secret_N7UND0UgjKTVK-Uodkm0Hg_xSvEMPvz"
)

# Use an in-memory SQLite DB for Airflow's metadata — must be set before any Airflow import
os.environ.setdefault(
    "AIRFLOW__DATABASE__SQL_ALCHEMY_CONN", "sqlite:////tmp/airflow_test.db"
)
os.environ.setdefault("AIRFLOW__CORE__EXECUTOR", "LocalExecutor")
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")
# Bypass Airflow's custom structlog formatter which causes a circular import
# when airflow.utils is referenced before the airflow module is fully initialized
os.environ.setdefault("AIRFLOW__LOGGING__LOGGING_CONFIG_CLASS", "")


@pytest.fixture(scope="session", autouse=True)
def initialize_airflow_db():
    from airflow.utils import db

    db.initdb()


@pytest.fixture(scope="session")
def local_supabase() -> Client:
    """Supabase client pointed at the local seeded instance (supabase/seed.sql).
    Requires `supabase start` to be running."""
    return create_client(LOCAL_SUPABASE_URL, LOCAL_SUPABASE_KEY)
