"""Actions on QA findings.

After running a check from `checks.py` and applying per-POI LLM
judgment, use these helpers to apply the decisions:

  delete_from_sample_places(prod_conn, sample_id, place_ids)
      → DELETE these POIs from sample_places. Use for garbage names
        (placeholders, name==address on compound_building rows).

  write_merge_pair_csv(pairs, out_csv)
      → Write pairs in the id_a,id_b,score format expected by
        `dataplor_report_review.dupelex.merge_push.trigger_matches_process`.
        Use for missed dupes discovered in same_chain_close /
        residual_name_dupes.
"""
import csv


def delete_from_sample_places(prod_conn, sample_id, place_ids,
                              statement_timeout_ms=60_000):
    """DELETE the given place_ids from sample_places for a sample.
    Returns rowcount. Uses the `prod` role — `places_read` is read-only.
    """
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


def write_merge_pair_csv(pairs, out_csv, default_score=0.95):
    """Write pairs [(id_a, id_b), ...] to a CSV suitable for matches:process.

    Downstream: pass the CSV path to
    `dupelex.merge_push.trigger_matches_process`.
    """
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id_a", "id_b", "score"])
        for ida, idb in pairs:
            w.writerow([ida, idb, default_score])
    return out_csv
