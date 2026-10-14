# Tactician Labs

A Teamfight Tactics (TFT) analytics platform: a data pipeline and web app, inspired by [tactics.tools](https://tactics.tools). It crawls high-elo ranked matches from the Riot API, stores them in BigQuery, derives per-patch stats and automatically discovered team compositions, and serves them through a TanStack Start frontend. A Gemini-backed agent can also answer stats questions in plain English by writing SQL over the stats views.

## What it does

- **Ingests** ranked matches from Challenger, Grandmaster and Master players across every region, daily.
- **Archives** the raw match JSON to Google Cloud Storage and parses it into BigQuery.
- **Computes exact stats** (win, top-4, average placement, play rate) per patch for champions, traits, items, item pairs and comps, with integer counters rather than re-scanned aggregates.
- **Discovers compositions** by clustering board vectors with HDBSCAN, so comps are found from the data and not hand-listed.
- **Serves a frontend** with `/compositions`, `/units` (with best items, duos and trios per unit), `/items`, `/leaderboard` and a skeleton `/explorer`.
- **Answers questions in English** with a guarded text-to-SQL agent (`insights/`).

## Architecture

```
Riot API ──▶ Cloud Run Job `tft-ingest` (daily) ──▶ GCS   raw match JSON
                      │                         └──▶ BigQuery `tft`
                      │                               matches, participants, participant_units,
                      │                               unit_items, participant_traits, players
                      │                               + per-patch counters (*_totals) updated
                      │                                 in the same transaction as the inserts
                      ▼
          Cloud Run Job `tft-cluster-compositions` (daily, after ingest)
                      │   board vectors ─▶ HDBSCAN on a sample ─▶ assign every board
                      ▼
            BigQuery: compositions, participant_compositions

BigQuery views (stats, current_*) ──▶ TanStack Start server functions ──▶ React pages
                                  └─▶ Gemini text-to-SQL agent (read-only, views only)
```

The deployed path is Cloud Run Jobs, started by Cloud Scheduler and built by Cloud Build from a Developer Connect trigger. All of it, plus the GCS bucket, datasets, tables and views, is Terraform in `infra/gcp/` (see its [README](infra/gcp/README.md)). The Airflow DAGs in `dags/` are the same pipeline for local development and backfills.

### Design decisions

- **Exact counters, rates derived in views.** Every ingest write adds its matches to per-patch counter tables (`champion_totals`, `item_totals`, ...) with one MERGE per table, in the same transaction as the match inserts. Rates are never stored; views compute them with `SAFE_DIVIDE`. Each MERGE also subtracts the rows it replaces, so reloads and overlapping re-ingests never double count. `jobs.rebuild_stats --check` diffs the counters against a full recount.
- **Crash-safe writes.** Rows are staged with free load jobs, then moved by one transaction script. `matches` is inserted last, so a crash part-way leaves the match absent and it is simply re-ingested.
- **Crawl budget instead of crawling everything.** Masters are ~28k players and each costs a request, so the crawl takes every Challenger and Grandmaster, then Masters round-robin by LP rank until it finds 2,000 *new* matches per routing region.
- **Compositions from hand-built vectors, not the embedding.** A board's vector has a column per unit (weighted by items held and star level, so itemized carries and tanks dominate and filler barely counts) and per active trait, L2-normalised. HDBSCAN fits on a sample of 50k boards, every board in the patch is then assigned to its nearest comp (or left out if it is less similar than that comp's own boards), and the comp counters come from every assigned board. Each comp is then split into variants (sub-clusters that differ from it by a few units or traits, with what they add and drop), so near-duplicate comps are one comp with variants.
- **Guarded text-to-SQL.** The agent dry-runs each query first and refuses anything that is not a single SELECT over an allow-listed set of views, or that would bill over a byte cap. Errors go back to the model so it can retry. Full 3-item builds are a separate fixed-shape tool because they are too sparse to keep as counters.
- **Frontend reads views only.** Server functions hold the SQL (parameterized, byte-capped, cached) and the build fails if one reaches the client bundle.

## Repository layout

| Path | What is there |
|---|---|
| `include/riot_api/` | Riot client: regions, retry/backoff, league and match endpoints, the high-elo crawl |
| `include/db/` | Parsing matches into rows, BigQuery writers, reference-data seeding |
| `include/data_aggregation/` | Counter SQL and the composition clustering |
| `include/jobs/` | Entry points for the Cloud Run jobs and maintenance commands |
| `include/insights/` | The text-to-SQL agent and its prompt |
| `dags/` | Airflow DAGs (local equivalent of the jobs) |
| `src/` | TanStack Start + React + Tailwind v4 + shadcn/ui frontend |
| `infra/gcp/` | Terraform: GCS, BigQuery tables and views, Cloud Run, Scheduler, Cloud Build |
| `tests/` | pytest suite with a fake BigQuery that checks rows against the Terraform schemas |

## Getting started

Prerequisites: Python (via [uv](https://docs.astral.sh/uv/)), Node, Docker, Terraform, and the gcloud CLI.

1. **Credentials.** Local runs use Application Default Credentials:
   ```sh
   gcloud auth application-default login
   export GOOGLE_CLOUD_PROJECT=<your-project>   # BQ_DATASET defaults to `tft`
   ```
   Put `RIOT_API_KEY` and `GEMINI_API_KEY` in `.env`. Riot development keys expire every 24 hours; scheduled runs need a Personal key. `GEMINI_API_KEY` is not needed with `SKIP_EMBEDDINGS=1`.
2. **Infrastructure.** From `infra/gcp/`, copy `terraform.tfvars.example` to `terraform.tfvars`, fill it in, then:
   ```sh
   terraform init
   terraform apply -input=false -var project_id=<your-project>
   ```
3. **Data.** Seed a small default dataset (below), or run the ingest.
4. **Frontend.** `npm install && npm run dev` (http://localhost:3000).

## Commands

Run Python commands from the repo root with `PYTHONPATH=include`.

### Data

```sh
# Seed Set 18 reference data, then load the archived matches (idempotent; doubles as a reset)
PYTHONPATH=include python -m db.seed_default_data [--skip-embeddings] [--limit N]

# Only champions / traits / items, from include/db/reference_data/
PYTHONPATH=include python -m db.seed_reference_data

# Load any archived day from GCS into BigQuery (skips matches already loaded)
PYTHONPATH=include python -m jobs.load_gcs_matches --prefix tft/matches/<version>/<date>/ [--reload] [--skip-embeddings]
```

### Stats

```sh
# Recompute the per-patch counter tables from the match tables
PYTHONPATH=include python -m jobs.rebuild_stats [--table NAME ...] [--patch X|latest]

# Report any counters that disagree with a recount (writes nothing)
PYTHONPATH=include python -m jobs.rebuild_stats --check

# Fill stored champion/item names and per-board summaries from the reference tables
PYTHONPATH=include python -m jobs.backfill_names [--table participant_units|unit_items|participants]
```

### Composition clustering

```sh
# Cluster a patch's boards into comps and replace its rows in `compositions`
# and `participant_compositions` (default: the latest patch)
PYTHONPATH=include python -m jobs.cluster_compositions [--patch X] [--min-cluster-size N] [--sample-size N] [--seed N]

# Print the comps it would find and write nothing; use this to tune --min-cluster-size
PYTHONPATH=include python -m jobs.cluster_compositions --dry-run --min-cluster-size 40
```

`--min-cluster-size` is the smallest group of boards HDBSCAN will call a comp (default `MIN_CLUSTER_FRACTION` of the sample, at least 25 boards). Lower it to find rarer comps and more variants; raise it for fewer, broader comps. Run `--dry-run` with a few values and check that the comps you expect are present and not duplicated before trusting them. Variants are printed under their comp. Nothing is written if no comps are found.

### Ask questions in English

```sh
# Needs GEMINI_API_KEY and GEMINI_SQL_MODEL (the model that writes the SQL)
PYTHONPATH=include python -m insights.nl_to_sql "which champions have the best top 4 rate"
```

The output ends with the SQL that ran. The model's rules, column glossary and worked examples are in `include/insights/prompt.py`; the views it may query are listed in `prompt.VIEWS`.

### Frontend

```sh
npm run dev         # dev server on port 3000
npm run build
npm run typecheck
docker compose up   # same, in a container with your gcloud credentials mounted
```

The server functions read BigQuery with your Application Default Credentials. Set `GOOGLE_CLOUD_PROJECT` and, optionally, `BQ_DATASET` and `BQ_LOCATION` (default `us-central1`). `src/routeTree.gen.ts` is generated; commit it after adding a route.

### Airflow (local, optional)

The DAGs run through the [Astro CLI](https://www.astronomer.io/docs/astro/cli/overview) in Docker:

```sh
astro dev start           # Airflow UI at http://localhost:8080
astro dev parse           # DAG integrity check
astro dev pytest          # run tests/ inside the Airflow container
```

Production does not use Airflow; the Cloud Run jobs run the same code.

### Tests

```sh
# Host-side tests that do not need Airflow
uv sync
PYTHONPATH=include uv run pytest --noconftest tests/insights

# Everything except live-service tests, inside the Airflow image (what CI runs)
astro dev pytest -- -m "not integration"
```

Tests marked `integration` call live Riot or BigQuery and are excluded in CI.

### Infrastructure

```sh
cd infra/gcp
terraform plan  -input=false -var project_id=<your-project> -out=plan
terraform apply -input=false plan
```

Tables and views are defined in `infra/gcp/bigquery.tf`, with column layouts in `infra/gcp/bigquery/<table>.json` and view SQL in `infra/gcp/bigquery/views/`. There are no SQL migrations; change a table by editing its JSON and applying.

## Status

Work in progress. The ingest, stats, clustering and text-to-SQL pieces work end to end; the `/explorer` page is a skeleton, and the text-to-SQL agent does not yet handle every multi-step question.

## Legal

Tactician Labs isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all associated properties are trademarks or registered trademarks of Riot Games, Inc.
