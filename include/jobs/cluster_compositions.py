"""Cluster a patch's boards into compositions.

Run with `python -m jobs.cluster_compositions` (PYTHONPATH must include `include/`).

Reads every board in the patch (the latest one unless --patch is given), finds the
comps with HDBSCAN on a sample, assigns every board to its nearest comp, and
replaces that patch's rows in `compositions` and `participant_compositions`. It
runs as its own Cloud Run Job after the ingest because it needs the whole patch,
while the ingest is split into per-region tasks.

With --dry-run it prints the comps and writes nothing, to tune --min-cluster-size.
"""

import argparse
import sys

from data_aggregation.compositions import (
    MIN_CLUSTER_SIZE,
    SAMPLE_SIZE,
    cluster_patch,
    latest_patch,
)
from db.bq import make_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--patch", help="matches.game_version to cluster (default: the latest)")
    parser.add_argument(
        "--sample-size",
        type=int,
        default=SAMPLE_SIZE,
        help="boards the comps are fitted on; all boards are assigned afterwards",
    )
    parser.add_argument(
        "--min-cluster-size",
        type=int,
        help=f"smallest comp, in sample boards (default: 0.3%% of the sample, at least {MIN_CLUSTER_SIZE})",
    )
    parser.add_argument("--seed", type=int, default=0, help="seed for the sample")
    parser.add_argument("--dry-run", action="store_true", help="print the comps, write nothing")
    args = parser.parse_args(argv)

    client = make_client()
    patch = args.patch or latest_patch(client)
    if patch is None:
        print("No patches yet: ingest some matches first")
        return 1

    variants: list[dict] = []
    comps = cluster_patch(
        client,
        patch,
        sample_size=args.sample_size,
        min_cluster_size=args.min_cluster_size,
        seed=args.seed,
        dry_run=args.dry_run,
        variants_out=variants,
    )
    if args.dry_run:
        for comp in sorted(comps, key=lambda c: -c["boards"]):
            average = comp["placement_sum"] / comp["boards"]
            carries = ", ".join(comp["carries"]) or "-"
            print(
                f"{comp['comp_id']:>14}  {comp['label']:<30} {comp['category'] or '-':<14} "
                f"boards={comp['boards']:<7} "
                f"avg_place={average:.2f}  carries: {carries}"
            )
            for variant in sorted(
                (v for v in variants if v["comp_id"] == comp["comp_id"]),
                key=lambda v: -v["boards"],
            ):
                variant_average = variant["placement_sum"] / variant["boards"]
                print(
                    f"{'':>14}    {variant['label']:<44} "
                    f"boards={variant['boards']:<7} avg_place={variant_average:.2f}"
                )
    return 0 if comps else 1


if __name__ == "__main__":
    sys.exit(main())
