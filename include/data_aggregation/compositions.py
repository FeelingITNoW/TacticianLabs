"""Composition clustering: group a patch's boards into comps from hand-built vectors.

Each board (one player in one match) becomes a vector with one column per
feature seen in the patch:

- `u:<champion>`: 1 + the number of items the unit holds (1-4), so a unit with
  three items weighs four times an itemless one and the main carries dominate
  the comp. With duplicate copies the one holding the most items counts.
- `t:<trait>`: the trait's `tier_current` times TRAIT_WEIGHT, for active traits
  only (`tier_current > 0`, the same rule as `trait_totals`).

Rows are L2-normalised, so euclidean distance orders boards like cosine.
HDBSCAN finds the comps on a random sample of the patch (it doesn't need the
number of comps, and boards that fit none stay out as noise). Every board in the
patch is then assigned to its nearest comp, or left unassigned when it is less
similar than the comp's own boards are. A cluster whose own boards are not alike
(HDBSCAN will group leftover off-meta boards into a blob) is dropped, not
reported as a comp. The comps' counters are exact: they come
from every assigned board, not from the sample.

Star levels play no part in the vectors; they are only reported per comp. Only ranked
boards are clustered, since the match tables also hold Challengers' normal games.
"""

import hashlib
from array import array
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone

import numpy as np
from google.cloud import bigquery
from scipy import sparse
from sklearn.cluster import HDBSCAN
from sklearn.preprocessing import normalize

from db.bq import insert_from_staging_sql, run_query, staged, table_ref, with_retry
from riot_api.constants import TFT_RANKED_QUEUE_ID

TRAIT_WEIGHT = 1.0
SAMPLE_SIZE = 20_000
MIN_CLUSTER_SIZE = 30
MIN_CLUSTER_FRACTION = 0.003  # of the sample, when that is more than MIN_CLUSTER_SIZE
THRESHOLD_PERCENTILE = 5  # a board must be at least as similar as 95% of its comp's sample
MIN_COHESION = 0.5  # clusters whose threshold is below this aren't comps
MIN_FREQUENCY = 0.25  # units and traits on fewer of a comp's boards aren't listed
CORE_FREQUENCY = 0.5  # units on at least this share of a comp's boards give its id
CARRY_ITEMS = 2.0  # a listed unit holding this many items on average is a carry
ASSIGN_CHUNK = 50_000

UNIT = "u:"
TRAIT = "t:"

BOARDS_SQL = """
WITH item_counts AS (
  SELECT match_id, puuid, slot, COUNT(*) AS items
  FROM `{unit_items}`
  GROUP BY match_id, puuid, slot
),
unit_features AS (
  SELECT
    u.match_id, u.puuid,
    CONCAT('u:', u.champion) AS feature,
    MAX(1 + COALESCE(i.items, 0)) AS value,
    MAX(u.star) AS star
  FROM `{participant_units}` AS u
  LEFT JOIN item_counts AS i USING (match_id, puuid, slot)
  GROUP BY u.match_id, u.puuid, u.champion
),
trait_features AS (
  SELECT match_id, puuid, CONCAT('t:', trait) AS feature, tier_current AS value, 0 AS star
  FROM `{participant_traits}`
  WHERE tier_current > 0
),
features AS (
  SELECT * FROM unit_features
  UNION ALL
  SELECT * FROM trait_features
)
SELECT
  p.match_id, p.puuid, p.played_at, p.placement,
  ARRAY_AGG(STRUCT(f.feature, f.value, f.star)) AS features
FROM `{participants}` AS p
JOIN `{matches}` AS m ON m.match_id = p.match_id
JOIN features AS f ON f.match_id = p.match_id AND f.puuid = p.puuid
WHERE m.game_version = @patch AND m.queue_id = {ranked_queue}
GROUP BY p.match_id, p.puuid, p.played_at, p.placement
""".replace("{ranked_queue}", str(TFT_RANKED_QUEUE_ID))


@dataclass
class Boards:
    match_ids: np.ndarray
    puuids: np.ndarray
    played_at: list[str]
    placements: np.ndarray
    features: list[str]  # sorted; "u:<champion>" or "t:<trait>"
    raw: sparse.csr_matrix  # units: 1 + items, traits: tier_current
    stars: sparse.csr_matrix  # units: star level
    vectors: sparse.csr_matrix  # weighted and L2-normalised, what gets clustered

    def __len__(self) -> int:
        return len(self.placements)


@dataclass
class Clusters:
    centroids: np.ndarray  # (comps, features), unit length
    thresholds: np.ndarray  # lowest similarity at which a board still joins the comp
    sample_size: int


# --- Reading ----------------------------------------------------------------


def latest_patch(client: bigquery.Client) -> str | None:
    """The patch with the newest match, the same one the current_* views use."""
    rows = run_query(
        client,
        f"SELECT patch FROM `{table_ref(client, 'patch_totals')}` "
        "ORDER BY last_played_at DESC LIMIT 1",
    )
    return rows[0]["patch"] if rows else None


def fetch_names(client: bigquery.Client) -> dict[str, str]:
    """Display names for champion and trait api names."""
    rows = run_query(
        client,
        f"SELECT api_name, name FROM `{table_ref(client, 'champions')}`\n"
        "UNION ALL\n"
        f"SELECT api_name, name FROM `{table_ref(client, 'traits')}`",
    )
    return {row["api_name"]: row["name"] for row in rows if row["name"]}


def fetch_boards(client: bigquery.Client, patch: str) -> Boards:
    sql = BOARDS_SQL.format(
        **{
            name: table_ref(client, name)
            for name in ("unit_items", "participant_units", "participant_traits", "participants", "matches")
        }
    )
    config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("patch", "STRING", patch)]
    )
    # Not materialised: build_boards turns each row into compact arrays as it
    # arrives, since a patch has hundreds of thousands of boards of ~15 features.
    rows = with_retry(lambda: client.query(sql, job_config=config).result())
    return build_boards(rows)


def build_boards(rows: Iterable[dict]) -> Boards:
    """Boards from rows of (match_id, puuid, played_at, placement, features), where
    features is a list of {feature, value, star}."""
    codes: dict[str, int] = {}
    match_ids, puuids, played_at, placements = [], [], [], []
    indptr = array("q", [0])
    columns, values, stars = array("i"), array("f"), array("f")
    for row in rows:
        match_ids.append(row["match_id"])
        puuids.append(row["puuid"])
        stamp = row["played_at"]
        played_at.append(stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp))
        placements.append(row["placement"])
        for feature in row["features"]:
            columns.append(codes.setdefault(feature["feature"], len(codes)))
            values.append(feature["value"])
            stars.append(feature["star"] or 0)
        indptr.append(len(columns))

    # Columns in sorted order, so the same patch always yields the same layout
    features = sorted(codes)
    remap = np.zeros(len(codes), dtype=np.int32)
    for new, name in enumerate(features):
        remap[codes[name]] = new
    cols = remap[np.array(columns, dtype=np.int32)]
    shape = (len(placements), len(features))
    pointers = np.array(indptr, dtype=np.int64)

    def matrix(data: array) -> sparse.csr_matrix:
        # Each matrix gets its own copy of the structure: sort_indices() reorders the
        # column indices in place, which would leave a matrix sharing them misaligned
        built = sparse.csr_matrix(
            (np.array(data, dtype=np.float32), cols.copy(), pointers.copy()), shape=shape
        )
        built.sort_indices()
        return built

    raw, star_levels = matrix(values), matrix(stars)
    weights = sparse.diags(
        np.array(
            [TRAIT_WEIGHT if name.startswith(TRAIT) else 1.0 for name in features],
            dtype=np.float32,
        )
    )
    return Boards(
        match_ids=np.array(match_ids, dtype=object),
        puuids=np.array(puuids, dtype=object),
        played_at=played_at,
        placements=np.array(placements, dtype=np.int64),
        features=features,
        raw=raw,
        stars=star_levels,
        vectors=normalize((raw @ weights).tocsr()) if len(placements) else raw,
    )


# --- Clustering -------------------------------------------------------------


def fit_clusters(
    vectors: sparse.csr_matrix,
    sample_size: int = SAMPLE_SIZE,
    min_cluster_size: int | None = None,
    seed: int = 0,
) -> Clusters | None:
    """Find the comps on a random sample of the boards. None when it finds none."""
    total = vectors.shape[0]
    if total == 0:
        return None
    rng = np.random.default_rng(seed)
    chosen = np.sort(rng.choice(total, size=min(total, sample_size), replace=False))
    sample = vectors[chosen]
    size = min_cluster_size or max(MIN_CLUSTER_SIZE, int(MIN_CLUSTER_FRACTION * len(chosen)))
    if len(chosen) < size:
        return None

    labels = HDBSCAN(min_cluster_size=size).fit_predict(sample.toarray())
    centroids, thresholds = [], []
    for label in sorted(set(labels) - {-1}):
        members = sample[labels == label]
        centroid = normalize(np.asarray(members.mean(axis=0)))[0]
        threshold = np.percentile(members @ centroid, THRESHOLD_PERCENTILE)
        if threshold < MIN_COHESION:
            continue
        centroids.append(centroid)
        thresholds.append(threshold)
    if not centroids:
        return None
    return Clusters(
        centroids=np.array(centroids, dtype=np.float32),
        thresholds=np.array(thresholds, dtype=np.float32),
        sample_size=len(chosen),
    )


def assign(vectors: sparse.csr_matrix, clusters: Clusters) -> tuple[np.ndarray, np.ndarray]:
    """(comp index or -1 for each board, its similarity to the nearest comp)."""
    labels = np.empty(vectors.shape[0], dtype=np.int64)
    similarity = np.empty(vectors.shape[0], dtype=np.float32)
    for start in range(0, vectors.shape[0], ASSIGN_CHUNK):
        sims = vectors[start : start + ASSIGN_CHUNK] @ clusters.centroids.T
        best = sims.argmax(axis=1)
        best_sim = sims[np.arange(len(best)), best]
        labels[start : start + ASSIGN_CHUNK] = np.where(
            best_sim >= clusters.thresholds[best], best, -1
        )
        similarity[start : start + ASSIGN_CHUNK] = best_sim
    return labels, np.clip(similarity, 0.0, 1.0)


# --- Summaries --------------------------------------------------------------


def display_name(names: dict[str, str], api_name: str) -> str:
    return names.get(api_name) or api_name.split("_")[-1]


def _feature_stats(boards: Boards, members: np.ndarray) -> tuple[list[dict], list[dict]]:
    """Units and traits on enough of the members' boards, most common first."""
    count = len(members)
    raw = boards.raw[members]
    present = raw.getnnz(axis=0)
    totals = np.asarray(raw.sum(axis=0)).ravel()
    star_totals = np.asarray(boards.stars[members].sum(axis=0)).ravel()

    units, traits = [], []
    for column in np.flatnonzero(present / count >= MIN_FREQUENCY):
        feature, boards_with = boards.features[column], int(present[column])
        entry = {"api_name": feature[2:], "frequency": round(boards_with / count, 4)}
        if feature.startswith(UNIT):
            # value = 1 + items
            entry["avg_items"] = round(float(totals[column] - boards_with) / boards_with, 4)
            entry["avg_star"] = round(float(star_totals[column]) / boards_with, 4)
            units.append(entry)
        else:
            entry["avg_tier"] = round(float(totals[column]) / boards_with, 4)
            traits.append(entry)
    for entries in (units, traits):
        entries.sort(key=lambda e: (-e["frequency"], e["api_name"]))
    return units, traits


def _comp_label(names, units, traits, carries) -> str | None:
    trait = max(traits, key=lambda t: (t["frequency"] * t["avg_tier"], t["api_name"]), default=None)
    carry = carries[0] if carries else (units[0]["api_name"] if units else None)
    parts = [display_name(names, x) for x in (trait and trait["api_name"], carry) if x]
    return " ".join(parts) or None


def _comp_id(units: list[dict], carries: list[str]) -> str:
    core = [u["api_name"] for u in units if u["frequency"] >= CORE_FREQUENCY]
    core = core or [u["api_name"] for u in units[:3]]
    key = "|".join(sorted(core)) + "#" + "|".join(sorted(carries))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def summarize(
    boards: Boards,
    labels: np.ndarray,
    similarity: np.ndarray,
    names: dict[str, str],
    patch: str,
    sample_size: int,
    clustered_at: datetime | None = None,
) -> tuple[list[dict], list[dict]]:
    """Rows for `compositions` and `participant_compositions`.

    Comps are numbered biggest first, so when two share a hash the bigger keeps
    the plain id and the other gets "-2".
    """
    stamp = (clustered_at or datetime.now(timezone.utc)).isoformat()
    sizes = np.bincount(labels[labels >= 0]) if (labels >= 0).any() else np.zeros(0, int)
    comp_ids: dict[int, str] = {}
    comps: list[dict] = []
    taken: set[str] = set()

    for label in sorted(np.flatnonzero(sizes), key=lambda i: (-sizes[i], i)):
        members = np.flatnonzero(labels == label)
        units, traits = _feature_stats(boards, members)
        carries = [
            u["api_name"]
            for u in sorted(units, key=lambda u: (-u["avg_items"], -u["frequency"], u["api_name"]))
            if u["avg_items"] >= CARRY_ITEMS
        ]
        base = comp_id = _comp_id(units, carries)
        suffix = 2
        while comp_id in taken:
            comp_id, suffix = f"{base}-{suffix}", suffix + 1
        taken.add(comp_id)
        comp_ids[int(label)] = comp_id

        placements = boards.placements[members]
        comps.append(
            {
                "patch": patch,
                "comp_id": comp_id,
                "label": _comp_label(names, units, traits, carries) or comp_id,
                "boards": int(len(members)),
                "matches": int(np.unique(boards.match_ids[members]).size),
                "placement_sum": int(placements.sum()),
                "top4_count": int((placements <= 4).sum()),
                "win_count": int((placements == 1).sum()),
                "units": units,
                "traits": traits,
                "carries": carries,
                "sample_size": sample_size,
                "clustered_at": stamp,
            }
        )

    assignments = [
        {
            "match_id": str(boards.match_ids[i]),
            "puuid": str(boards.puuids[i]),
            "played_at": boards.played_at[i],
            "patch": patch,
            "comp_id": comp_ids[int(labels[i])],
            "similarity": round(float(similarity[i]), 4),
        }
        for i in np.flatnonzero(labels >= 0)
    ]
    return comps, assignments


# --- Writing ----------------------------------------------------------------


def write_compositions(
    client: bigquery.Client, patch: str, compositions: list[dict], assignments: list[dict]
) -> None:
    """Replace the patch's comps and board assignments in one transaction, so a
    rerun (or a crash part-way) never leaves them out of step with each other."""
    rows = {"compositions": compositions, "participant_compositions": assignments}
    with staged(client, rows) as staging:
        statements = []
        for name in rows:
            statements.append(
                f"DELETE FROM `{table_ref(client, name)}` WHERE patch = @patch;"
            )
            if name in staging:
                statements.append(insert_from_staging_sql(client, name, staging[name]))
        script = "\n".join(["BEGIN TRANSACTION;", *statements, "COMMIT TRANSACTION;"])
        run_query(
            client, script, [bigquery.ScalarQueryParameter("patch", "STRING", patch)]
        )


def cluster_patch(
    client: bigquery.Client,
    patch: str,
    sample_size: int = SAMPLE_SIZE,
    min_cluster_size: int | None = None,
    seed: int = 0,
    dry_run: bool = False,
) -> list[dict]:
    """Cluster one patch's boards and replace its comps. Returns the comps.

    Writes nothing when there are no boards or no comps were found, so a bad
    run can't wipe the previous result.
    """
    boards = fetch_boards(client, patch)
    if not len(boards):
        print(f"No boards for patch {patch}")
        return []
    clusters = fit_clusters(boards.vectors, sample_size, min_cluster_size, seed)
    if clusters is None:
        print(f"No comps found among {len(boards)} boards for patch {patch}")
        return []

    labels, similarity = assign(boards.vectors, clusters)
    comps, assignments = summarize(
        boards, labels, similarity, fetch_names(client), patch, clusters.sample_size
    )
    print(
        f"Patch {patch}: {len(comps)} comps, {len(assignments)} of {len(boards)} "
        f"boards assigned (fitted on {clusters.sample_size})"
    )
    if not dry_run:
        write_compositions(client, patch, comps, assignments)
    return comps
