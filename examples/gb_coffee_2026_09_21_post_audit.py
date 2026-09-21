"""End-to-end example: run the Phase-4.5 post-audit + Phase-5b unmerge
against the 2026-09-21 GB coffee incident.

Reproduces the audit that flagged 71 wrongly-merged POIs across
Starbucks + Costa + Caffè Nero UK and reversed them via
`matches:process --split`. Meant as documentation for the two new
modules; treat it as a template for the next batch, not a runbook —
paths, sample ids, and the enriched-CSV location are workflow-
specific.

Usage:
    python examples/gb_coffee_2026_09_21_post_audit.py \\
        --pairs /path/to/pushed_pairs.csv \\
        --enrich /path/to/enriched_places.csv \\
        --presales-tools /path/to/presales_tools \\
        --admin-id 42476
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path


def _load_pairs(path: Path) -> list[tuple[int, int]]:
    with path.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        return [(int(row["id_a"]), int(row["id_b"])) for row in r]


def _load_enrich(path: Path) -> dict[int, dict]:
    """Enriched CSV columns: place_id, postcode, chain_id, provisional,
    parent_id. Provisional is 'true'/'false'; parent_id may be blank
    for root places."""
    meta: dict[int, dict] = {}
    with path.open(encoding="utf-8") as f:
        r = csv.DictReader(f)
        for row in r:
            pid = int(row["place_id"])
            meta[pid] = {
                "postcode": row.get("postcode") or "",
                "chain_id": row.get("chain_id") or "",
                "provisional": (row.get("provisional") or "").lower() == "true",
                "parent_id": int(row["parent_id"]) if (row.get("parent_id") or "").strip() else None,
            }
    return meta


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pairs", type=Path, required=True,
                    help="CSV with id_a,id_b of the pairs pushed in Phase 4.")
    ap.add_argument("--enrich", type=Path, required=True,
                    help="CSV with place_id,postcode,chain_id,provisional,"
                         "parent_id (from dupelex.enrich, or your own).")
    ap.add_argument("--presales-tools", type=Path, required=True,
                    help="Path to the presales_tools checkout (needed for "
                         "matches:process invocation).")
    ap.add_argument("--admin-id", type=int, required=True,
                    help="Admin id for attribution on prod (mine: 42476).")
    ap.add_argument("--country", default="gb",
                    help="Country code — 'gb' uses UK outward postcodes.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Compute reversals + write the CSV, do not push.")
    ap.add_argument("--out", type=Path, default=Path("./unmerge_pairs.csv"),
                    help="Where to write the split CSV before pushing.")
    ap.add_argument("--include-provisional-flip", action="store_true",
                    help="Also flag verified-into-provisional flips.")
    args = ap.parse_args(argv)

    from dataplor_report_review.dupelex import post_audit, unmerge

    pairs = _load_pairs(args.pairs)
    meta = _load_enrich(args.enrich)
    print(f"Loaded {len(pairs)} pushed pairs, metadata for {len(meta)} POIs.")

    candidates = post_audit.audit_merges(
        pairs, meta, country=args.country,
        include_provisional_flip=args.include_provisional_flip,
    )
    print(f"\nReversal candidates: {len(candidates)}")
    for c in candidates[:10]:
        print(f"  pid={c.place_id}")
        for r in c.failure_modes:
            print(f"    - {r}")
    if len(candidates) > 10:
        print(f"  ... and {len(candidates) - 10} more.")

    if not candidates:
        print("Nothing to unmerge. Exiting.")
        return 0

    written, proc = unmerge.unmerge(
        pushed_pairs=pairs,
        reversal_pids=[c.place_id for c in candidates],
        csv_path=args.out,
        admin_id=args.admin_id,
        presales_tools_root=args.presales_tools,
        dry_run=args.dry_run,
    )
    print(f"\nWrote split CSV: {written}")
    print(f"matches:process --split exit: {proc.returncode}")
    if proc.stdout:
        for line in proc.stdout.splitlines()[-10:]:
            print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
