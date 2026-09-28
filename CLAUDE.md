# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A TFT (Teamfight Tactics) analytics pipeline, heading toward a tactics.tools clone. The roadmap is in `.github/prompts/plan-tacticsToolsClone.prompt.md`. It has three loosely coupled parts:

1. **Airflow (Astronomer) ETL**: `dags/` + `include/`. It pulls high-elo matches from the Riot API, archives the raw JSON to Google Cloud Storage (GCS), and parses the matches into Supabase Postgres, embedding each participant's comp with Gemini into pgvector. A second DAG then aggregates win, top-4, average-placement and play rates.
2. **Supabase**: `supabase/` holds the schema migrations, a large `seed.sql` used by the tests, and the local config (API on :54321, DB on :54322).
3. **Frontend**: `src/` is TanStack Start + React + Vite (port 3000). It's early: one `/leaderboard` route that queries Supabase directly. `src/routeTree.gen.ts` is generated, so don't edit it by hand.

`main.tf` (Terraform) is deprecated: it provisioned a Backblaze B2 bucket for match archiving, since replaced by GCS (see the deprecation note at the top of the file for retiring it). `infra/gcp/` is the live Terraform root: it provisions the GCS bucket (`google_storage_bucket.tft_match_data`) plus everything to run ingestion as a Cloud Run Job in production (`include/jobs/ingest_matches.py`, image `Dockerfile.jobs`, deps `requirements-jobs.txt`), built by `cloudbuild.yaml` from a Developer Connect trigger and started daily by Cloud Scheduler. See `infra/gcp/README.md`. `main.py` is a placeholder.

## Commands

Airflow runs through the Astro CLI in Docker (`Dockerfile` = Astro Runtime 3.1, Python 3.12 inside the container):
- `astro dev start` / `astro dev restart`: Airflow UI at http://localhost:8080
- `astro dev pytest`: runs `tests/` inside the Airflow container (this is how `pytest.log` was produced)
- `astro dev pytest tests/dags/test_upsert_json_to_bucket_and_db.py -- -k TestParseMatchData`: run a single test/class
- `astro dev parse`: DAG integrity check (uses `.astro/test_dag_integrity_default.py`, don't edit it)

Supabase (local):
- `npx supabase start`: required for tests that use the `local_supabase` fixture, which read the seed data
- `npx supabase db reset`: reapply migrations + `seed.sql`
- `npx supabase migration new <name>`: new migration in `supabase/migrations/`

Frontend: `npm run dev` (or `docker compose up`, which uses `Dockerfile.node`), `npm run build`. There is no JS test or lint setup.

Host-side Python uses uv (`pyproject.toml`, Python 3.14, deps in the `dev` group): `uv sync`, `uv run pytest ...`. Note that the tests import Airflow, which is only installed in the Astro container.

## Architecture notes

**Import paths.** DAGs import from `include/` as top-level packages (`from riot_api.match_api import ...`, `from db.parse_match_data import ...`). This works because the `Dockerfile` adds `/usr/local/airflow/include` to `PYTHONPATH` and `pyproject.toml` sets pytest `pythonpath = [".", "include", "dags"]`. Keep using this style, not `include.x`.

**Dependencies live in four places:** `requirements.txt` (Astro/Airflow image), `requirements-jobs.txt` (Cloud Run job image), `pyproject.toml` (uv host env), and `requirements-data.txt` (the Node dev container). Add Airflow-runtime deps to `requirements.txt`, and to `requirements-jobs.txt` too if `include/` code used by the job needs them.

**`upsert_json_to_bucket_and_db` DAG (daily):**
`collect_match_ids_task.expand(region=RIOT_REGIONS)` → `collect_matches_task` → fans out to `upload_to_gcs_task` (key `tft/matches/{ddragon_version}/{utc_date}/{match_id}.json`) and `upsert_to_db_task`. `upsert_players_task` must finish before the DB upsert. Tasks are `async` and use `httpx.AsyncClient`. The Riot fetch tasks run with `max_active_tis_per_dagrun=1` to respect rate limits.

**Riot API (`include/riot_api/`).** This is the canonical client. `constants.py` has the regions, the platform→routing map (`RIOT_REGIONS_MAP`) and `HIGH_ELO_TIERS`. League endpoints use the platform (`NA1`), match endpoints use the routing region (`AMERICAS`). Use `riot_get_with_retry` (429/backoff). `riot_data_retrieval.py` is only a re-export shim. `league_api.get_league_entries` returns the full apex-tier list; `include/db/upsert_players.py` builds `players`/`player_ranked_stats` rows straight from it (no per-player calls). Riot dev keys expire every 24h, so scheduled runs need a Personal key.

**Parsing (`include/db/parse_match_data.py`).** It skips anything that isn't ranked (`queue_id != 1100`), builds rows for `participants` (with a 768-dim Gemini `gemini-embedding-001` embedding, one batched `get_embeddings` call per match), `traits` and `units`, and upserts `matches`. It also upserts a `players` row per participant first, because `participants.puuid` has an FK to `players` and lobbies include players outside the crawled tiers. Writes are idempotent (participants/traits upsert on their PKs, units are delete-then-insert per match) since the daily look-back windows overlap; `filter_new_match_ids` skips already-ingested matches before fetching. Supabase writes go through `_execute_with_retry` for transient PostgREST errors.

**Stats (`calculate_tft_stats` DAG + `include/data_aggregation/`).** It reads the reference tables (`champions`, `traits`/`traits_reference`, `items`), which `include/db/seed_tft16_reference_data.py` fills from the root `tft-*.json` Data Dragon files (Set 16 only). It then maps a task per entity and upserts into `champion_stats` / `trait_stats` / `item_stats`. Check the latest migrations before relying on table names: `traits` is both the per-participant trait table and, in migration `20260504215516`, a reference table. `traits_reference` was added to resolve that clash.

**Config/secrets.** DAGs read `os.environ["supabase_url"]`, `["supabase_key"]`, `["GEMINI_API_KEY"]`, `RIOT_API_KEY` (or `API_KEY`) from `.env`. GCS is accessed through the Airflow connection `google_cloud_default` (GCSHook), which is defined in `airflow_settings.yaml` (gitignored) with a service account keyfile; the Cloud Run job instead uses its runtime service account's default credentials, no key needed. The tests default to `LOCAL_SUPABASE_URL=http://host.docker.internal:54321` because they run inside the Astro container.

**Tests.** `tests/conftest.py` points Airflow at a SQLite metadata DB and runs `initdb` once per session. `tests/dags/test_constants.py` holds full sample Riot match payloads (ranked and unranked) for parser tests. `tests/dags/test_dag_example.py` asserts that every DAG imports cleanly and has tags and retries.

**CI (`.github/workflows/`).** `lint.yml` runs `ruff check` and `tsc --noEmit`. Ruff is pinned to `0.15.9` (both in the workflow and as a dev dependency) with an explicit `[tool.ruff.lint] select` matching ruff's own conservative defaults (`E4`, `E7`, `E9`, `F`) — without that, a version bump (or `ruff-action` falling back to "latest" when it can't detect a pin) pulls in a much larger ruleset (isort, pylint, flake8-datetimez, ...) this codebase was never written against. `tests.yml` starts a local Supabase (db + kong + postgrest only), builds the `Dockerfile` image, and runs `pytest tests -m "not integration"` inside it against that local Supabase, with dummy `GEMINI_API_KEY`/`RIOT_API_KEY` values (the parsing tests patch `get_embeddings` and never call Riot, so no real keys are needed there). Tests marked `@pytest.mark.integration` (in `TestCollectMatchIds`) hit the live Riot API and are excluded in CI.
