"""
Snapshot the CommunityDragon data the seed needs into db/reference_data/cdragon-tft<set>.json.

Data Dragon has no square champion icon (its champion art is a wide splash), so champion
icons come from CommunityDragon's in-game `tileIcon`. CommunityDragon also has each trait's
style (bronze, silver, ...) per breakpoint, which Data Dragon lacks. The snapshot is committed
so seeding stays offline and reproducible.

Usage:
    PYTHONPATH=include python -m db.fetch_cdragon [--set 18] [--patch 16.19]
"""

import argparse
import json
from pathlib import Path
from urllib.request import Request, urlopen

REFERENCE_DIR = Path(__file__).parent / "reference_data"
BASE = "https://raw.communitydragon.org"


def snapshot_path(tft_set: int) -> Path:
    return REFERENCE_DIR / f"cdragon-tft{tft_set}.json"


def icon_url(patch: str, asset: str) -> str:
    """The PNG for a game asset path such as assets/characters/x/x_square.tex."""
    return f"{BASE}/{patch}/game/{asset.lower().removesuffix('.tex')}.png"


def build_snapshot(raw: dict, tft_set: int, patch: str) -> dict:
    mutator = f"TFTSet{tft_set}"
    tft = next(s for s in raw["setData"] if s["mutator"] == mutator)
    return {
        "patch": patch,
        "set": tft_set,
        "champions": {
            c["apiName"]: icon_url(patch, c["tileIcon"])
            for c in tft["champions"]
            if c.get("tileIcon")
        },
        "trait_styles": {
            t["apiName"]: [e["style"] for e in t["effects"]] for t in tft["traits"]
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", type=int, default=18, dest="tft_set")
    parser.add_argument("--patch", default="16.19", help="CommunityDragon patch directory")
    args = parser.parse_args()
    request = Request(
        f"{BASE}/{args.patch}/cdragon/tft/en_us.json", headers={"User-Agent": "tactician-labs"}
    )
    with urlopen(request) as response:
        raw = json.load(response)
    snapshot = build_snapshot(raw, args.tft_set, args.patch)
    snapshot_path(args.tft_set).write_text(json.dumps(snapshot, indent=1, sort_keys=True) + "\n")
    print(f"{len(snapshot['champions'])} champions, {len(snapshot['trait_styles'])} traits")


if __name__ == "__main__":
    main()
