"""Composition clustering: group a patch's boards into comps from hand-built vectors.

Each board (one player in one match) becomes a vector with one column per
feature seen in the patch:

- `u:<champion>`: (UNIT_BASE_WEIGHT + the number of items the unit holds) times a
  factor for its star level (STAR_WEIGHTS), so itemized, starred-up units (the
  carries and tanks) dominate the comp while itemless 1-star filler barely counts
  and two or three of them swapping between boards doesn't split a comp. With
  duplicate copies the one holding the most items counts.
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

Star levels also give each comp its category (see categorize), with the carries'
costs. The per-unit stats (`avg_items`, `avg_star`) come from the raw counts, not
the clustering weights above. Only ranked
boards are clustered, since the match tables also hold Challengers' normal games.
"""

import hashlib
from array import array
from collections import Counter
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
UNIT_BASE_WEIGHT = 0.25  # what an itemless unit weighs; each item adds 1
STAR_WEIGHTS = {2: 1.5, 3: 2.5}  # multiplier by star level; 1 star (and anything else) is 1.0
SAMPLE_SIZE = 50_000
MIN_CLUSTER_SIZE = 25
MIN_CLUSTER_FRACTION = 0.002  # of the sample, when that is more than MIN_CLUSTER_SIZE
# a board is assigned to a comp when it is at least as similar to the centroid as this
# percentile of the comp's own sampled boards, so about 96.5% of those would pass
THRESHOLD_PERCENTILE = 3.5
MIN_COHESION = 0.5  # clusters whose threshold is below this aren't comps
MIN_FREQUENCY = 0.25  # units and traits on fewer of a comp's boards aren't listed
CORE_FREQUENCY = 0.5  # units on at least this share of a comp's boards give its id
CARRY_ITEMS = 2.0  # a listed unit holding this many items on average is a carry
REROLL_STAR = 2.5  # a carry of a reroll cost at this average star level is rerolled for
REROLL_COSTS = (1, 2, 3)
ASSIGN_CHUNK = 50_000

# Variants: sub-clusters inside one comp that differ from it by a few units or traits.
MIN_VARIANT_SIZE = 40  # smallest variant, in sampled boards
VARIANT_FRACTION = 0.02  # of the comp's sampled boards, when that is more than MIN_VARIANT_SIZE
VARIANT_SAMPLE = 8_000  # boards of one comp the variants are fitted on
VARIANT_MIN_DIFF = 0.3  # a unit or trait is a difference when its frequency moves this much
VARIANT_MAX_UNIT_DIFF = 4  # a sub-cluster differing by more units than this isn't a variant
VARIANT_LABEL_DIFFS = 3  # differences named in a variant's label

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
    raw: sparse.csr_matrix  # units: 1 + items, traits: tier_current (what the stats use)
    stars: sparse.csr_matrix  # units: star level
    vectors: sparse.csr_matrix  # item, star and trait weighted, L2-normalised; what gets clustered

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


def fetch_costs(client: bigquery.Client) -> dict[str, int]:
    """Champion costs (1-5) by api name."""
    rows = run_query(
        client,
        f"SELECT api_name, cost FROM `{table_ref(client, 'champions')}` WHERE cost > 0",
    )
    return {row["api_name"]: row["cost"] for row in rows}


def fetch_boards(client: bigquery.Client, patch: str) -> Boards:
    sql = BOARDS_SQL.format(
        **{
            name: table_ref(client, name)
            for name in (
                "unit_items",
                "participant_units",
                "participant_traits",
                "participants",
                "matches",
            )
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
        played_at.append(
            stamp.isoformat() if hasattr(stamp, "isoformat") else str(stamp)
        )
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
            (np.array(data, dtype=np.float32), cols.copy(), pointers.copy()),
            shape=shape,
        )
        built.sort_indices()
        return built

    raw, star_levels = matrix(values), matrix(stars)
    return Boards(
        match_ids=np.array(match_ids, dtype=object),
        puuids=np.array(puuids, dtype=object),
        played_at=played_at,
        placements=np.array(placements, dtype=np.int64),
        features=features,
        raw=raw,
        stars=star_levels,
        vectors=(
            normalize(clustering_weights(raw, star_levels, features))
            if len(placements)
            else raw
        ),
    )


def clustering_weights(
    raw: sparse.csr_matrix, stars: sparse.csr_matrix, features: list[str]
) -> sparse.csr_matrix:
    """`raw` reweighted for clustering: units by items and star level, traits by tier.

    `raw` and `stars` are built from the same structure, so their data line up.
    """
    is_unit = np.array([name.startswith(UNIT) for name in features])[raw.indices]
    items = raw.data - 1.0  # units are stored as 1 + items
    star_factor = np.ones_like(raw.data)
    for star, factor in STAR_WEIGHTS.items():
        star_factor[stars.data == star] = factor
    data = np.where(
        is_unit, (UNIT_BASE_WEIGHT + items) * star_factor, raw.data * TRAIT_WEIGHT
    ).astype(np.float32)
    return sparse.csr_matrix((data, raw.indices, raw.indptr), shape=raw.shape)


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
    size = min_cluster_size or max(
        MIN_CLUSTER_SIZE, int(MIN_CLUSTER_FRACTION * len(chosen))
    )
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


def assign(
    vectors: sparse.csr_matrix, clusters: Clusters
) -> tuple[np.ndarray, np.ndarray]:
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


def _feature_stats(
    boards: Boards, members: np.ndarray
) -> tuple[list[dict], list[dict]]:
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
            entry["avg_items"] = round(
                float(totals[column] - boards_with) / boards_with, 4
            )
            entry["avg_star"] = round(float(star_totals[column]) / boards_with, 4)
            units.append(entry)
        else:
            entry["avg_tier"] = round(float(totals[column]) / boards_with, 4)
            traits.append(entry)
    for entries in (units, traits):
        entries.sort(key=lambda e: (-e["frequency"], e["api_name"]))
    return units, traits


def _comp_label(names, units, traits, carries) -> str | None:
    trait = max(
        traits,
        key=lambda t: (t["frequency"] * t["avg_tier"], t["api_name"]),
        default=None,
    )
    carry = carries[0] if carries else (units[0]["api_name"] if units else None)
    parts = [display_name(names, x) for x in (trait and trait["api_name"], carry) if x]
    return " ".join(parts) or None


def categorize(
    units: list[dict], carries: list[str], costs: dict[str, int]
) -> str | None:
    """How the comp is played, from its carries' costs and average star levels.

    Carries of cost 1-3 that average REROLL_STAR or more are rerolled for, and the
    cost with the most of them makes it a 1, 2 or 3 cost reroll (a tie goes to the
    more itemized carry; carries are ordered that way). Otherwise it levels: fast 9
    when more carries are 5 costs than 4 costs, else fast 8. None when no carry has
    a known cost.
    """
    stars = {u["api_name"]: u["avg_star"] for u in units}
    known = [c for c in carries if costs.get(c)]
    if not known:
        return None
    rerolled = [
        c for c in known if costs[c] in REROLL_COSTS and stars.get(c, 0) >= REROLL_STAR
    ]
    if rerolled:
        counts = Counter(costs[c] for c in rerolled)
        most = max(counts.values())
        cost = next(costs[c] for c in rerolled if counts[costs[c]] == most)
        return f"{cost}_cost_reroll"
    counts = Counter(costs[c] for c in known)
    return "fast_9" if counts[5] > counts[4] else "fast_8"


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
    costs: dict[str, int] | None = None,
) -> tuple[list[dict], list[dict]]:
    """Rows for `compositions` and `participant_compositions`. `costs` (champion api
    name -> cost) gives each comp its category.

    Comps are numbered biggest first, so when two share a hash the bigger keeps
    the plain id and the other gets "-2".
    """
    stamp = (clustered_at or datetime.now(timezone.utc)).isoformat()
    sizes = (
        np.bincount(labels[labels >= 0]) if (labels >= 0).any() else np.zeros(0, int)
    )
    comp_ids: dict[int, str] = {}
    comps: list[dict] = []
    taken: set[str] = set()

    for label in sorted(np.flatnonzero(sizes), key=lambda i: (-sizes[i], i)):
        members = np.flatnonzero(labels == label)
        units, traits = _feature_stats(boards, members)
        carries = [
            u["api_name"]
            for u in sorted(
                units, key=lambda u: (-u["avg_items"], -u["frequency"], u["api_name"])
            )
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
                "category": categorize(units, carries, costs or {}),
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


# --- Variants ---------------------------------------------------------------


def _variant_diff(
    comp: tuple[list[dict], list[dict]], variant: tuple[list[dict], list[dict]]
) -> list[dict]:
    """Units and traits whose frequency in the variant differs from the comp's by
    VARIANT_MIN_DIFF or more, biggest difference first. A feature too rare to be
    listed (under MIN_FREQUENCY) counts as 0."""
    diffs = []
    for kind, comp_entries, variant_entries in (
        ("unit", comp[0], variant[0]),
        ("trait", comp[1], variant[1]),
    ):
        base = {e["api_name"]: e["frequency"] for e in comp_entries}
        new = {e["api_name"]: e["frequency"] for e in variant_entries}
        for name in base.keys() | new.keys():
            before, after = base.get(name, 0.0), new.get(name, 0.0)
            if abs(after - before) >= VARIANT_MIN_DIFF:
                diffs.append(
                    {
                        "api_name": name,
                        "kind": kind,
                        "change": "added" if after > before else "removed",
                        "frequency": after,
                        "family_frequency": before,
                    }
                )
    diffs.sort(
        key=lambda d: (-abs(d["frequency"] - d["family_frequency"]), d["api_name"])
    )
    return diffs


def _variant_id(comp_id: str, diffs: list[dict]) -> str:
    key = comp_id + "#" + "|".join(sorted(f"{d['change']}:{d['api_name']}" for d in diffs))
    return hashlib.sha1(key.encode()).hexdigest()[:12]


def _variant_label(names: dict[str, str], label: str, diffs: list[dict]) -> str:
    parts = [
        ("+" if d["change"] == "added" else "-") + display_name(names, d["api_name"])
        for d in diffs[:VARIANT_LABEL_DIFFS]
    ]
    return " ".join([label, *parts])


def find_variants(
    boards: Boards,
    comp_ids: np.ndarray,
    comp_labels: dict[str, str],
    names: dict[str, str],
    patch: str,
    clustered_at: datetime | None = None,
    seed: int = 0,
) -> tuple[list[dict], np.ndarray]:
    """Split each comp's boards into variants. `comp_ids` has each board's comp (None
    when it has none).

    A variant is a sub-cluster of one comp's boards, fitted the same way as the comps
    but on that comp alone, that differs from the comp by at least one and at most
    VARIANT_MAX_UNIT_DIFF units (or by traits). Boards in no variant are the comp's
    base build. Returns the `composition_variants` rows and each board's variant id
    (None for none). The variants' counters are exact over their assigned boards.
    """
    stamp = (clustered_at or datetime.now(timezone.utc)).isoformat()
    variant_ids = np.full(len(boards), None, dtype=object)
    rows: list[dict] = []
    taken: set[str] = set()

    for comp_id in sorted({c for c in comp_ids if c is not None}):
        members = np.flatnonzero(comp_ids == comp_id)
        if len(members) < 2 * MIN_VARIANT_SIZE:
            continue
        vectors = boards.vectors[members]
        sample = min(len(members), VARIANT_SAMPLE)
        size = max(MIN_VARIANT_SIZE, int(VARIANT_FRACTION * sample))
        clusters = fit_clusters(vectors, VARIANT_SAMPLE, size, seed)
        if clusters is None:
            continue
        labels, _ = assign(vectors, clusters)
        comp = _feature_stats(boards, members)

        found = []
        for label in np.unique(labels[labels >= 0]):
            chosen = members[labels == label]
            units, traits = _feature_stats(boards, chosen)
            diffs = _variant_diff(comp, (units, traits))
            if not diffs or sum(d["kind"] == "unit" for d in diffs) > VARIANT_MAX_UNIT_DIFF:
                continue
            found.append((chosen, units, traits, diffs))

        for chosen, units, traits, diffs in sorted(found, key=lambda f: -len(f[0])):
            base = variant_id = _variant_id(comp_id, diffs)
            suffix = 2
            while variant_id in taken:
                variant_id, suffix = f"{base}-{suffix}", suffix + 1
            taken.add(variant_id)
            variant_ids[chosen] = variant_id
            placements = boards.placements[chosen]
            rows.append(
                {
                    "patch": patch,
                    "comp_id": comp_id,
                    "variant_id": variant_id,
                    "label": _variant_label(names, comp_labels.get(comp_id, comp_id), diffs),
                    "boards": int(len(chosen)),
                    "matches": int(np.unique(boards.match_ids[chosen]).size),
                    "placement_sum": int(placements.sum()),
                    "top4_count": int((placements <= 4).sum()),
                    "win_count": int((placements == 1).sum()),
                    "units": units,
                    "traits": traits,
                    "diff": diffs,
                    "clustered_at": stamp,
                }
            )
    return rows, variant_ids


# --- Writing ----------------------------------------------------------------


def write_compositions(
    client: bigquery.Client,
    patch: str,
    compositions: list[dict],
    assignments: list[dict],
    variants: list[dict] | None = None,
) -> None:
    """Replace the patch's comps, their variants and the board assignments in one
    transaction, so a rerun (or a crash part-way) never leaves them out of step."""
    rows = {
        "compositions": compositions,
        "composition_variants": variants or [],
        "participant_compositions": assignments,
    }
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
    variants_out: list[dict] | None = None,
) -> list[dict]:
    """Cluster one patch's boards and replace its comps and their variants. Returns the
    comps; the variants are appended to `variants_out` when it is given.

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
    names = fetch_names(client)
    comps, assignments = summarize(
        boards,
        labels,
        similarity,
        names,
        patch,
        clusters.sample_size,
        costs=fetch_costs(client),
    )

    assigned = np.flatnonzero(labels >= 0)
    comp_ids = np.full(len(boards), None, dtype=object)
    comp_ids[assigned] = [a["comp_id"] for a in assignments]
    variants, variant_ids = find_variants(
        boards, comp_ids, {c["comp_id"]: c["label"] for c in comps}, names, patch, seed=seed
    )
    for board, assignment in zip(assigned, assignments):
        assignment["variant_id"] = variant_ids[board]

    print(
        f"Patch {patch}: {len(comps)} comps with {len(variants)} variants, "
        f"{len(assignments)} of {len(boards)} boards assigned "
        f"(fitted on {clusters.sample_size})"
    )
    if variants_out is not None:
        variants_out.extend(variants)
    if not dry_run:
        write_compositions(client, patch, comps, assignments, variants)
    return comps
