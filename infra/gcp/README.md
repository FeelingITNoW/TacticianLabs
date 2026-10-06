# GCP: Cloud Run ingest job

Runs `include/jobs/ingest_matches.py` daily as a Cloud Run Job. Each push to `main` that touches the job's code triggers a rebuild through Developer Connect and Cloud Build.

```
GitHub push ─▶ Developer Connect ─▶ Cloud Build (cloudbuild.yaml) ─▶ Artifact Registry
                                                                   └▶ gcloud run jobs update
Cloud Scheduler (06:00 UTC) ─▶ Cloud Run Job tft-ingest (4 tasks: AMERICAS / ASIA / EUROPE / SEA)
                                  └▶ Riot API ─▶ GCS (raw JSON) + BigQuery `tft` (parsed rows + Gemini embeddings)
Cloud Scheduler (10:00 UTC) ─▶ Cloud Run Job tft-cluster-compositions (same image)
                                  └▶ BigQuery `tft`: board vectors ─▶ comps + board assignments
```

The match archive lives in `google_storage_bucket.tft_match_data` here; the job authenticates to it with the `tft-ingest-runner` service account's default credentials, no key needed.

## One-time setup

1. **Link the repo in Developer Connect.** This needs a GitHub OAuth step, which Terraform can't do. Use the plain **Developer Connect → Connections** console page, not Cloud Run's "Continuously deploy from a repository" wizard — that one also spins up its own Cloud Run *service* as a side effect, which isn't part of this setup and is just a stray resource to delete afterwards (`gcloud run services delete <name> --region=<region>`).

   Console → Developer Connect → *Connections* → **Create**, choose GitHub, pick a region — it does **not** need to match `var.region` — and install the GitHub app on `FeelingITNoW/clone.tools`. Then **Link repository**. Find the connection and copy the repository link's full resource name for `git_repository_link`:
   ```sh
   gcloud developer-connect connections list --location=<connection-region>
   gcloud developer-connect connections git-repository-links list \
     --connection=<connection-name> --location=<connection-region> --format='value(name)'
   ```
   If `<connection-region>` differs from `var.region`, also set `developer_connect_region` in `terraform.tfvars` — the Cloud Build trigger has to live in the connection's region, but nothing else in this file does.

2. **Create the secrets, add their values, then apply everything else.**
   ```sh
   cp terraform.tfvars.example terraform.tfvars   # fill in
   terraform init
   terraform apply -target=google_secret_manager_secret.job

   for id in gemini-api-key riot-api-key; do
     read -rsp "$id: " v; echo; printf '%s' "$v" | gcloud secrets versions add "$id" --data-file=-
   done

   terraform apply
   ```
   `riot-api-key` must be a **Personal** (or Production) key. Development keys expire after 24 hours, so a daily job using one would start failing the next day.

3. **Seed the default data** (needs `gcloud auth application-default login`): Set 18 reference tables plus the matches archived under `tft/matches/16.19.1/2026-09-28/`.
   ```sh
   GOOGLE_CLOUD_PROJECT=<project_id> PYTHONPATH=include python -m db.seed_default_data --limit 20 --skip-embeddings   # quick check
   GOOGLE_CLOUD_PROJECT=<project_id> GEMINI_API_KEY=... PYTHONPATH=include python -m db.seed_default_data              # full: 2,700 matches, one Gemini call each
   ```
   `python -m jobs.load_gcs_matches --prefix tft/matches/<version>/<date>/` loads any other archived day.

4. **Build the first image.** Terraform creates the job with a placeholder image. Either push to `main`, or run:
   ```sh
   gcloud builds trigger run tft-ingest-deploy --region=us-central1 --branch=main
   ```

## Day to day

- Run now: `gcloud run jobs execute tft-ingest --region=us-central1 --wait`
- Smoke test a single region: `gcloud run jobs execute tft-ingest --region=us-central1 --tasks=1 --update-env-vars=REGIONS=SG2,MAX_MATCHES=5`
- Logs: `gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="tft-ingest"' --limit=100`

## Local runs

`storage.Client()` in `include/jobs/ingest_matches.py` uses Application Default Credentials. Outside Cloud Run, set those up once with:
```sh
gcloud auth application-default login
```
and Docker runs (`docker run ... tft-ingest`) will pick them up from `~/.config/gcloud` if you mount it, e.g. `-v ~/.config/gcloud:/home/app/.config/gcloud:ro`. Set `SKIP_GCS_UPLOAD=1` to skip the bucket entirely for a quick DB-only smoke test.

## BigQuery

`bigquery.tf` creates the `tft` dataset, a `tft_staging` dataset whose tables expire after a day, and one table per file in `bigquery/`. Primary and foreign keys are recorded `NOT ENFORCED`. The provider only takes single-column foreign keys, so composite ones are noted in the table descriptions. Tables have `deletion_protection` on (the provider default), so a change that forces replacement fails at apply instead of dropping data.

The job writes with free load jobs into `tft_staging`, then one SQL script per 50-match chunk. That script's deletes are bounded by `played_at` partitions and clustered on `match_id`, so it scans little. The same script also MERGEs the chunk into the per-patch `*_totals` counter tables, reading only the staged rows and the rows being replaced. Both stay well inside the 1 TB/month free query tier at current volumes.

### Stats tables and views

`champion_totals`, `trait_totals`, `item_totals`, `champion_item_totals` and `patch_totals` hold exact integer counters per patch, kept current by the ingest. The `champion_stats`, `trait_stats`, `item_stats` and `champion_item_stats` views (templates in `bigquery/views/`) derive the rates, and `current_*_stats` restrict them to the latest patch with display names. The job's 1Gi of memory is unaffected: the counting runs inside BigQuery.

**Migrating from the old stats tables.** `champion_stats`, `trait_stats` and `item_stats` used to be tables and are now views of the same names. Their tables have `deletion_protection`, so Terraform can't swap them. Do this once:
```sh
terraform state rm 'google_bigquery_table.linked["champion_stats"]' \
  'google_bigquery_table.linked["trait_stats"]' 'google_bigquery_table.linked["item_stats"]'
for t in champion_stats trait_stats item_stats; do bq rm -f -t "$PROJECT:tft.$t"; done
terraform plan    # only creates (totals tables + views); no per-match table changes
terraform apply
PYTHONPATH=include python -m jobs.rebuild_stats          # backfill the totals from existing matches
PYTHONPATH=include python -m jobs.rebuild_stats --check  # should report 0 mismatches
```
Run the backfill before the next ingest. Until it runs, the first write for a patch would start that patch's totals from only the new matches, and `rebuild_stats` would then correct it.

### Embeddings

The ingest job runs with `SKIP_EMBEDDINGS=1` (Terraform variable `skip_embeddings`, default `true`): it writes `participants` rows with an empty `embedding` and never calls Gemini, since nothing reads the embeddings yet and comp clustering uses its own vectors. To turn them back on, set `skip_embeddings = false` and apply. To fill in the gaps, run `python -m jobs.load_gcs_matches --prefix tft/matches/<version>/<date>/ --reload` for each day, which re-embeds from the GCS archive. The `GEMINI_API_KEY` secret stays in place so that switch is all it takes.

### Compositions

`compositions` and `participant_compositions` hold the comps found in each patch and the comp each board was assigned to (boards that fit none have no row). They are rewritten per patch by a second Cloud Run Job, `tft-cluster-compositions` (`include/jobs/cluster_compositions.py`), which runs from the same image as the ingest (cloudbuild.yaml deploys both) at 10:00 UTC, after the ingest's 3 hour timeout. It is separate because it needs the whole patch, while the ingest is split into per-region tasks. It has 2 vCPU and 4Gi, since it holds the patch's boards in memory (as sparse matrices) and fits HDBSCAN on a 20k-board sample. The `composition_stats` view derives the rates and `current_composition_stats` restricts it to the latest patch.

After the first `terraform apply`, and whenever you want to tune the clustering:
```sh
PYTHONPATH=include python -m jobs.cluster_compositions --dry-run   # print the comps, write nothing
PYTHONPATH=include python -m jobs.cluster_compositions             # write them
gcloud run jobs execute tft-cluster-compositions --region=us-central1 --wait
```
Until the first Cloud Build run the job still points at Google's placeholder image, so executing it fails.

## Cost notes

Everything scales to zero between runs. Cloud Run Jobs bill vCPU-seconds while tasks run, and the free tier is 180k vCPU-s a month. Four 1-vCPU tasks running about 25 minutes a day stay inside it. Check the first few runs' durations. Most of that time is spent waiting on Riot's rate limits, not on CPU. Secret Manager (3 secrets), Scheduler (1 job), Artifact Registry (last 5 images) and GCS (write/read of a few MB/day) all fit in their free tiers.
