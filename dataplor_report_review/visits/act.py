"""Actions on visits verdicts.

Two paths are available for DELIVERY_GAP verdicts:

  A. Remove the POI from `sample_places` — the client won't see it in
     the export, avoiding a delivered POI with silently missing visits.
     Use when the POI would confuse the client (e.g. a basketball court
     showing up in a retail audit with no visits).

  B. Keep the POI and flag it in the delivery note — the client sees it,
     understands why visits are missing, and can factor that into their
     analysis. Use when the POI's existence is important even without
     visits (e.g. a landmark that anchors surrounding coverage).

Which of the two applies depends on the customer's use case; the LLM
verdict function should attach a `mode` field to each verdict indicating
DROP or KEEP_AND_FLAG. This module provides both operators.
"""
import csv


def drop_from_sample(prod_conn, sample_id, place_ids,
                     statement_timeout_ms=60_000):
    """DELETE the given place_ids from sample_places for the sample.
    Returns rowcount. Uses `prod` role."""
    if not place_ids:
        return 0
    with prod_conn.cursor() as c:
        c.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        c.execute(
            "DELETE FROM sample_places WHERE sample_id=%s AND place_id = ANY(%s)",
            (sample_id, list(place_ids)),
        )
        n = c.rowcount
    prod_conn.commit()
    return n


def write_delivery_note(verdicts, out_csv, include_labels=("DELIVERY_GAP",)):
    """Write a CSV note the delivery owner can attach to the sample.
    One row per verdicted POI in `include_labels`."""
    rows = [v for v in verdicts if v.get("verdict") in include_labels]
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["place_id", "name", "category", "l1_group", "verdict", "reason"])
        for v in rows:
            w.writerow([v.get("id"), v.get("name"), v.get("category"),
                       v.get("l1"), v.get("verdict"), v.get("reason")])
    return out_csv, len(rows)
