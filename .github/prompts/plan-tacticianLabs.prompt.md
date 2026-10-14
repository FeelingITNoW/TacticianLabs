# Plan: Tactician Labs (RAG & Analytics)

## Decisions
- Google AI Studio (Gemini API key) for embeddings (`text-embedding-004`, 768 dims)
- RAG responses = structured data (ranked item/comp lists with win rates, not prose)
- All regions: NA1, EUW1, EUNE1, KR, SG2, JP1, BR1, LA1, LA2, OC1
- Dark-themed dashboard (tactics.tools aesthetic)
- FastAPI service in Docker Compose for RAG/analytics API
- Supabase pgvector for vector storage

---

## Phase 1 — Schema & Infrastructure

### 1.1 Enable pgvector
- New Supabase migration: `CREATE EXTENSION IF NOT EXISTS vector;`

### 1.2 New analytics tables (new migration file)
- `composition_stats` (comp_key TEXT PK, trait_combination TEXT[], avg_placement FLOAT, top4_rate FLOAT, win_rate FLOAT, play_count INT, patch TEXT, updated_at TIMESTAMP)
- `unit_stats` (character_id TEXT PK, avg_placement FLOAT, play_count INT, top4_rate FLOAT, win_rate FLOAT, avg_tier FLOAT, patch TEXT)
- `item_stats` (item_name TEXT PK, avg_placement FLOAT, usage_count INT, usage_rate FLOAT, win_rate FLOAT, top4_rate FLOAT)
- `unit_item_stats` (character_id TEXT, item_name TEXT, avg_placement FLOAT, usage_count INT, win_rate FLOAT, top4_rate FLOAT, PK: (character_id, item_name))
- `composition_trends` (comp_key TEXT, date DATE, avg_placement FLOAT, play_count INT, win_rate FLOAT, PK: (comp_key, date))
- `composition_embeddings` (comp_key TEXT FK, embedding VECTOR(768), document TEXT, updated_at TIMESTAMP)

### 1.3 Supabase RPC function (in migration)
- `match_compositions(query_embedding vector(768), match_count int)` — cosine similarity search returning comp_key + similarity score

### 1.4 Multi-region expansion
- `include/riot_api/constants.py`: expand RIOT_REGIONS from ["SG2"] to ["NA1","EUW1","EUNE1","KR","SG2","JP1","BR1","LA1","LA2","OC1"]
- Verify region→routing mapping covers all new regions

---

## Phase 2 — Analytics Aggregation DAG

New file: `dags/compute_analytics.py`

Tasks (with dependencies):
1. `aggregate_composition_stats` — GROUP BY sorted trait arrays across participants+traits, compute avg_placement, win_rate, top4_rate (placement ≤ 4), play_count per patch
2. `aggregate_unit_stats` — GROUP BY character_id across units+participants, compute placement stats
3. `aggregate_item_stats` — UNNEST item_names array, GROUP BY item, aggregate placement stats + usage_rate (usage_count / total_matches)
4. `aggregate_unit_item_stats` — UNNEST items per unit row, GROUP BY (character_id, item_name) — *depends on tasks 1, 2, 3*
5. `compute_trends` — Insert daily snapshots into composition_trends by slicing over game_datetime — *depends on task 1*
6. Schedule: `@daily`, runs AFTER the existing `ingest_matches_to_gcs_and_bigquery` DAG completes (use `ExternalTaskSensor`)

Key SQL pattern for compositions: join participants → traits, sort trait names array, string_agg as comp_key, aggregate placement.

---

## Phase 3 — Embeddings & RAG

### 3.1 Requirements
- Add `google-generativeai` to `requirements.txt`

### 3.2 New DAG task in `compute_analytics.py`
Task: `generate_composition_embeddings`
- For each row in composition_stats, build a document string:
  `"TFT Composition: {traits}. Core units: {top units by frequency}. Avg placement: {X}. Win rate: {X}%. Play rate: {X}%."`
- Batch embed documents using `genai.embed_content(model="models/text-embedding-004", content=docs)`
- Upsert into `composition_embeddings` table
- *Depends on task 1 (composition_stats)*

### 3.3 RAG query logic (in FastAPI `api/routers/rag.py`)
- Embed user query via `text-embedding-004`
- Call Supabase RPC `match_compositions(query_embedding, 10)`
- Join result comp_keys with composition_stats for full data
- Return ranked list with avg_placement, win_rate, trait_combination

---

## Phase 4 — FastAPI Service

### New directory structure
```
api/
  main.py
  requirements.txt
  Dockerfile
  routers/
    compositions.py
    units.py
    items.py
    trends.py
    rag.py
  db.py          # Supabase client singleton
```

### Endpoints
- `GET /compositions` — paginated comp list (sort by win_rate/avg_placement/play_count)
- `GET /compositions/{comp_key}` — single comp with units, trends
- `GET /units` — all unit stats (sortable)
- `GET /units/{character_id}/bis` — top items for unit from unit_item_stats
- `GET /items` — item stats table
- `GET /trends?days=7` — top trending comps (biggest win_rate change over N days)
- `POST /rag/search` — body `{query: string}` → RAG composition search
- `POST /rag/bis` — body `{query: "Kaisa BIS"}` → parse unit name, query unit_item_stats sorted by win_rate

### docker-compose.yml addition
```yaml
api:
  build: ./api
  ports: ["8000:8000"]
  environment: [SUPABASE_URL, SUPABASE_KEY, GOOGLE_API_KEY]
```

### api/requirements.txt
fastapi, uvicorn, supabase, google-generativeai, python-dotenv

---

## Phase 5 — Frontend Revamp

### 5.1 Setup
- Install: `tailwindcss@latest`, `@tailwindcss/vite`, `recharts`, `lucide-react`
- Configure Tailwind with dark theme as default
- Install shadcn/ui components (Button, Card, Table, Badge, Input, Tabs)

### 5.2 New routes
- `/` — Dashboard: meta snapshot cards (top 3 comps, trending items), quick links
- `/compositions` — Tier list table with trait icons, sortable by win_rate / avg_placement / play_count; filter by trait
- `/compositions/$compKey` — Detail: trait breakdown, unit carousel with BIS items, trend sparkline
- `/units` — Sortable champion stats table with star tier icons
- `/units/$unitId` — Champion page: BIS item list with win rates, best comps featuring unit
- `/items` — Item stats table: usage rate, win rate, best carriers
- `/trends` — Recharts line charts for comp/item win rate over time (7d/30d toggle)
- `/ask` — Search input → calls `/rag/search` or `/rag/bis` → returns structured result cards

### 5.3 Shared components
- `StatCard` — metric display with label + value + delta
- `CompCard` — composition display (trait pills + unit icons)
- `BISList` — ranked item list with win rate badge
- `TrendChart` — Recharts LineChart with dark theme

### 5.4 API client
- `src/api/client.ts` — fetch wrapper pointing at FastAPI base URL
- `src/api/compositions.ts`, `units.ts`, `items.ts`, `trends.ts`, `rag.ts`

---

## Relevant Files to Modify

| File | Change |
|------|--------|
| `include/riot_api/constants.py` | Expand RIOT_REGIONS |
| `requirements.txt` | Add google-generativeai |
| `docker-compose.yml` | Add api service |
| `package.json` | Add Tailwind, Recharts, Lucide |
| `supabase/migrations/` | New migration files (pgvector, analytics tables) |
| `dags/ingest_matches_to_gcs_and_bigquery.py` | Multi-region support |

## New Files
- `supabase/migrations/XXXXXX_analytics_schema.sql`
- `dags/compute_analytics.py`
- `include/analytics/aggregation.py` (SQL queries for aggregation)
- `include/embeddings/google_embed.py` (embedding generation)
- `api/` directory (FastAPI service)
- `src/routes/compositions.tsx`, `units.tsx`, `items.tsx`, `trends.tsx`, `ask.tsx`
- `src/api/client.ts` and individual API files
- `src/components/` (StatCard, CompCard, BISList, TrendChart)

---

## Verification Steps
1. Run migrations → verify pgvector extension + all new tables exist in Supabase
2. Run `compute_analytics` DAG manually → check composition_stats has populated rows
3. Check embeddings table: `SELECT count(*) FROM composition_embeddings WHERE embedding IS NOT NULL`
4. Call `POST /rag/bis` with `{"query": "Kaisa BIS"}` → validated structured response
5. Call `POST /rag/search` with `{"query": "reroll kogmaw comp"}` → similarity search returns relevant comps
6. Frontend: navigate to /compositions and verify data renders with charts
7. Frontend: try the AI query page with "Kaisa BIS" and verify ranked item cards render
