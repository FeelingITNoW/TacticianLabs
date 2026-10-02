# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A TFT (Teamfight Tactics) analytics pipeline, heading toward a tactics.tools clone. The roadmap is in `.github/prompts/plan-tacticsToolsClone.prompt.md`. It has three loosely coupled parts:

1. **Airflow (Astronomer) ETL**: `dags/` + `include/`. It pulls high-elo matches from the Riot API, archives the raw JSON to Google Cloud Storage (GCS), and parses the matches into **BigQuery** (dataset `tft`), embedding each participant's comp with Gemini into a `REPEATED FLOAT64` column. A second DAG then rebuilds per-patch win, top-4, average-placement and play rates in SQL.
2. **BigQuery** is the relational store. Tables are defined in Terraform (`infra/gcp/bigquery.tf`, column layouts in `infra/gcp/bigquery/<table>.json`); there are no SQL migrations. Change a table by editing its JSON and applying Terraform.
3. **Frontend**: `src/` is TanStack Start + React + Vite (port 3000). It's early: one `/leaderboard` route. It still queries **Supabase** directly, which no longer receives new data. `supabase/` (old migrations, `seed.sql`, local config) is kept only until the frontend moves to BigQuery. `src/routeTree.gen.ts` is generated, so don't edit it by hand.

`infra/gcp/` is the live Terraform root: it provisions the GCS bucket (`google_storage_bucket.tft_match_data`), the BigQuery datasets and tables, plus everything to run ingestion as a Cloud Run Job in production (`include/jobs/ingest_matches.py`, image `Dockerfile.jobs`, deps `requirements-jobs.txt`), built by `cloudbuild.yaml` from a Developer Connect trigger and started daily by Cloud Scheduler. See `infra/gcp/README.md`. `main.py` is a placeholder.

## Commands

Airflow runs through the Astro CLI in Docker (`Dockerfile` = Astro Runtime 3.1, Python 3.12 inside the container):
- `astro dev start` / `astro dev restart`: Airflow UI at http://localhost:8080
- `astro dev pytest`: runs `tests/` inside the Airflow container (this is how `pytest.log` was produced)
- `astro dev pytest tests/dags/test_ingest_matches_to_gcs_and_bigquery.py -- -k TestParseMatchData`: run a single test/class
- `astro dev parse`: DAG integrity check (uses `.astro/test_dag_integrity_default.py`, don't edit it)

BigQuery:
- `cd infra/gcp && terraform apply`: create/alter datasets and tables
- `PYTHONPATH=include python -m db.seed_tft16_reference_data`: fill `champions`/`traits`/`items` from the root `tft-*.json` files
- Local runs use Application Default Credentials (`gcloud auth application-default login`); set `GOOGLE_CLOUD_PROJECT`, and `BQ_DATASET` if it isn't `tft`

Supabase (local, frontend only until it moves off): `npx supabase start`, `npx supabase db reset`.

Frontend: `npm run dev` (or `docker compose up`, which uses `Dockerfile.node`), `npm run build`. There is no JS test or lint setup.

Host-side Python uses uv (`pyproject.toml`, Python 3.14, deps in the `dev` group): `uv sync`, `uv run pytest ...`. Note that the tests import Airflow, which is only installed in the Astro container.

## Architecture notes

**Import paths.** DAGs import from `include/` as top-level packages (`from riot_api.match_api import ...`, `from db.parse_match_data import ...`). This works because the `Dockerfile` adds `/usr/local/airflow/include` to `PYTHONPATH` and `pyproject.toml` sets pytest `pythonpath = [".", "include", "dags"]`. Keep using this style, not `include.x`.

**Dependencies live in four places:** `requirements.txt` (Astro/Airflow image), `requirements-jobs.txt` (Cloud Run job image), `pyproject.toml` (uv host env), and `requirements-data.txt` (the Node dev container). Add Airflow-runtime deps to `requirements.txt`, and to `requirements-jobs.txt` too if `include/` code used by the job needs them.

**`ingest_matches_to_gcs_and_bigquery` DAG (daily):**
`collect_match_ids_task.expand(region=RIOT_REGIONS)` → `collect_matches_task` → fans out to `upload_to_gcs_task` (key `tft/matches/{ddragon_version}/{utc_date}/{match_id}.json`) and `upsert_to_bigquery_task`. `upsert_players_task` runs before the DB upsert. Both DAGs reach BigQuery through `BigQueryHook(gcp_conn_id="google_cloud_default").get_client()`. Tasks are `async` and use `httpx.AsyncClient`. The Riot fetch tasks run with `max_active_tis_per_dagrun=1` to respect rate limits.

**Riot API (`include/riot_api/`).** This is the canonical client. `constants.py` has the regions, the platform→routing map (`RIOT_REGIONS_MAP`) and `HIGH_ELO_TIERS`. League endpoints use the platform (`NA1`), match endpoints use the routing region (`AMERICAS`). Use `riot_get_with_retry` (429/backoff). `riot_data_retrieval.py` is only a re-export shim. `league_api.get_league_entries` returns the full apex-tier list; `include/db/upsert_players.py` builds `players`/`player_ranked_stats` rows straight from it (no per-player calls) and MERGEs them. Riot dev keys expire every 24h, so scheduled runs need a Personal key.

**BigQuery writes (`include/db/bq.py`).** Every writer stages rows into fresh tables in the `tft_staging` dataset with load jobs (free; tables expire after a day), then moves them with one SQL script, via `run_query`/`with_retry` (retries 5xx and concurrent-DML aborts). Primary and foreign keys are declared `NOT ENFORCED`; the writers keep them true. Every per-match table carries `played_at` and is day-partitioned on it.

**Parsing (`include/db/parse_match_data.py`).** `build_match_rows` is pure apart from the Gemini call: it skips anything that isn't ranked (`queue_id != 1100`) and returns rows keyed by table for `matches`, `players`, `participants` (with a 768-dim `gemini-embedding-001` embedding, one batched `get_embeddings` call per match), `participant_traits`, `participant_units` (keyed on `slot`, the unit's index on the board, so duplicate champions survive) and `unit_items`. `write_matches` parses a batch and `write_match_rows` replaces those matches in one script: delete `matches` first, delete-then-insert each child table, MERGE `players`, insert `matches` last, so a crash part-way leaves the match absent and it is re-ingested. `filter_new_match_ids` skips already-ingested matches before fetching.

**Stats (`calculate_tft_stats` DAG + `include/data_aggregation/`).** One task per stats table (`champion_stats`, `trait_stats`, `item_stats`), each rebuilding the whole table per `(patch, api_name)` in a single transaction. A board counts once per entity however many copies it holds; rates are over boards, `play_rate` over all boards in the patch, and `patch` is `matches.game_version`. Reference tables `champions`/`traits`/`items` are keyed on Riot's api name (e.g. `TFT_Item_BFSword`) and filled by `include/db/seed_tft16_reference_data.py` (Set 16 only for champions/traits).

**Config/secrets.** DAGs read `GEMINI_API_KEY` and `RIOT_API_KEY` (or `API_KEY`) from `.env`, plus optional `BQ_DATASET`/`BQ_STAGING_DATASET` (default `tft`/`tft_staging`). GCS and BigQuery are both accessed through the Airflow connection `google_cloud_default`, defined in `airflow_settings.yaml` (gitignored) with a service account keyfile; that account needs BigQuery Job User on the project and Data Editor on both datasets. The Cloud Run job instead uses its runtime service account's default credentials (granted in `infra/gcp/bigquery.tf`), no key needed.

**Tests.** `tests/conftest.py` points Airflow at a SQLite metadata DB and runs `initdb` once per session. Its `fake_bq` fixture (`FakeBigQuery`) records loads and queries instead of running them and checks every loaded row against the Terraform schema JSON, so a row/table mismatch fails a unit test. `tests/dags/test_constants.py` holds full sample Riot match payloads (ranked and unranked) for parser tests. `tests/dags/test_dag_example.py` asserts that every DAG imports cleanly and has tags and retries.

**CI (`.github/workflows/`).** `lint.yml` runs `ruff check` and `tsc --noEmit`. Ruff is pinned to `0.15.9` (both in the workflow and as a dev dependency) with an explicit `[tool.ruff.lint] select` matching ruff's own conservative defaults (`E4`, `E7`, `E9`, `F`) — without that, a version bump (or `ruff-action` falling back to "latest" when it can't detect a pin) pulls in a much larger ruleset (isort, pylint, flake8-datetimez, ...) this codebase was never written against. `tests.yml` builds the `Dockerfile` image and runs `pytest tests -m "not integration"` inside it, with dummy `GEMINI_API_KEY`/`RIOT_API_KEY` values (the parsing tests patch `get_embeddings` and never call Riot, and BigQuery is faked). Tests marked `@pytest.mark.integration` hit live services and are excluded in CI: `TestCollectMatchIds` (Riot API) and `TestStatsSqlCompiles` (dry-runs the stats SQL against real BigQuery; run it after `terraform apply`).
