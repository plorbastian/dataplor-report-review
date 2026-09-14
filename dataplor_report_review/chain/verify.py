"""Chain verification — confirm chain_id landed in prod + places_read after
the observations write and PTU cycle.

Two checks:
  1. Of the APPLY verdicts, how many places now have chain_id set to the
     expected slug in each role?
  2. Sample-level coverage: total chained POIs in the sample before vs after.
"""


def count_chain_applied(conn, verdicts):
    """Return (applied_correct, applied_wrong, still_null) for a set of
    verdicts with expected chain_id."""
    applied = 0
    wrong = 0
    null = 0
    if not verdicts:
        return 0, 0, 0
    ids = [v["place_id"] for v in verdicts]
    expected = {v["place_id"]: v["chain_id"] for v in verdicts}
    with conn.cursor() as c:
        c.execute("SELECT id, chain_id FROM places WHERE id = ANY(%s)", (ids,))
        for pid, chain in c.fetchall():
            exp = expected[pid]
            if chain is None:
                null += 1
            elif chain == exp:
                applied += 1
            else:
                wrong += 1
    return applied, wrong, null


def sample_chain_coverage(conn, sample_id):
    """Return (total, chained, unchained) for the sample."""
    with conn.cursor() as c:
        c.execute("""SELECT COUNT(*) AS total,
                            COUNT(*) FILTER (WHERE p.chain_id IS NOT NULL) AS chained,
                            COUNT(*) FILTER (WHERE p.chain_id IS NULL) AS unchained
                     FROM sample_places sp
                     JOIN places p ON p.id = sp.place_id
                     WHERE sp.sample_id = %s""", (sample_id,))
        return c.fetchone()


def full_check(prod_conn, read_conn, sample_id, apply_verdicts):
    """Consolidated verification against both roles."""
    prod_applied, prod_wrong, prod_null = count_chain_applied(prod_conn, apply_verdicts)
    read_applied, read_wrong, read_null = count_chain_applied(read_conn, apply_verdicts)
    p_total, p_chained, p_unchained = sample_chain_coverage(prod_conn, sample_id)
    r_total, r_chained, r_unchained = sample_chain_coverage(read_conn, sample_id)
    return {
        "sample_id": sample_id,
        "expected_apply": len(apply_verdicts),
        "prod": {"applied": prod_applied, "wrong": prod_wrong, "null": prod_null,
                 "sample_total": p_total, "sample_chained": p_chained},
        "places_read": {"applied": read_applied, "wrong": read_wrong, "null": read_null,
                        "sample_total": r_total, "sample_chained": r_chained},
        "parity": {
            "sample_totals_match": p_total == r_total,
            "sample_chained_match": p_chained == r_chained,
            "applied_match": prod_applied == read_applied,
        },
    }
