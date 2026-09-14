"""Phase 1 — filter raw dupelex CSV.gz down to the actionable subset.

A raw dupelex report over a large city sample can be tens of millions of pairs.
We want to keep only pairs where the pair carries at least one strong signal:

  - name_similarity >= 0.9
  - haversine distance < 50 meters (coord match)
  - exact_phone
  - exact_website
  - loc_parent_link (both share the same location_parent_id)

AND score >= 0.5. This typically collapses ~30M raw rows to ~15-25K actionable pairs.

Usage:
    from dupelex_llm_review.filter import filter_raw_dupelex
    filter_raw_dupelex(
        input_gz="dupelex_9990_514683.csv.gz",
        output_csv="dupelex_9990_actionable.csv",
        min_score=0.5,
    )
"""
import csv, gzip, json, os, time

STRONG_NAME_SIM = 0.9
CLOSE_COORDS_M = 50.0


def _parse_explain(explain_json):
    try:
        return json.loads(explain_json) if explain_json else {}
    except Exception:
        return {}


def _has_strong_signal(row, explain):
    try:
        if float(row.get("name_similarity") or 0) >= STRONG_NAME_SIM:
            return True, "name_sim"
    except (TypeError, ValueError):
        pass
    try:
        if float(row.get("haversine_m") or 99999) < CLOSE_COORDS_M:
            return True, "coords"
    except (TypeError, ValueError):
        pass
    if str(row.get("exact_phone", "")).lower() in ("true", "1", "t"):
        return True, "phone"
    if str(row.get("exact_website", "")).lower() in ("true", "1", "t"):
        return True, "website"
    if str(row.get("loc_parent_link", "")).lower() in ("true", "1", "t"):
        return True, "loc_parent"
    return False, ""


def filter_raw_dupelex(input_gz, output_csv, min_score=0.5, progress_every=500_000):
    """Stream through the raw dupelex .csv.gz and emit only actionable pairs.

    Returns (total_read, total_kept, output_path).
    """
    csv.field_size_limit(50 * 1024 * 1024)
    t0 = time.time()
    total = 0
    kept = 0
    with gzip.open(input_gz, "rt", encoding="utf-8", newline="") as fin, \
         open(output_csv, "w", encoding="utf-8", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = None
        for row in reader:
            total += 1
            try:
                sc = float(row.get("score") or 0)
            except (TypeError, ValueError):
                sc = 0
            if sc < min_score:
                continue
            explain = _parse_explain(row.get("explain"))
            has, which = _has_strong_signal(row, explain)
            if not has:
                continue
            row["strong_signal"] = which
            if writer is None:
                writer = csv.DictWriter(fout, fieldnames=list(row.keys()))
                writer.writeheader()
            writer.writerow(row)
            kept += 1
            if total % progress_every == 0:
                dt = time.time() - t0
                rate = int(total / dt) if dt > 0 else 0
                print(f"  read {total:,} rows  kept {kept:,}  elapsed {int(dt)}s  rate {rate}/s")

    dt = time.time() - t0
    print(f"DONE: total {total:,}  kept {kept:,}  time {int(dt)}s  -> {output_csv}")
    return total, kept, output_csv
