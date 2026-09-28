"""Scan a sample for the Javaria pattern: a chained POI whose
`business_category_id` is NOT in the brand's `business_category_ids`,
and which HAS visits populated in the DB.

Those visits are silently stripped when the `place_export` runs. The
export computes `is_core` for each place as

    is_core = place.business_category_id IN brand.business_category_ids

and any place where that evaluates false has its visitation data
dropped from the delivered CSV.

Bucket every chained POI in the sample by whether its category matches
its brand:

  in_business_cats       — cat is in the brand's `business_category_ids`
                           (is_core would be true; visits will land)
  outside                — cat is NOT in `business_category_ids`
                           (is_core is false or null; visits will be
                           stripped at export)
      → subset ``outside_with_visits`` is the Javaria set: the client
        will get the POI in the delivered CSV but with no visitation
        data even though the DB row has it.

CANONICAL FIX (per Javaria's diagram): update the place's
`business_category_id` to match one of the brand's
`business_category_ids`. Do NOT expand the brand's list to swallow the
place's odd category — the brand row should represent what the brand
actually IS, not accumulate every category the platform happens to
tag a store with.

Exception: a true sub-place (bakery inside a supermarket) legitimately
carries a different category. Those cases should keep their category
and lose the parent brand's visitation on purpose. The Javaria set is
the pool the operator reviews; not every row in it is a mis-tag.

Rows with no `chain_id` are excluded — the strip only fires on chained
POIs. Historical note: an earlier revision of this scanner also
inspected `core_1_category_ids` and `core_2_category_ids`, but those
fields are unused stale metadata (confirmed by their author) and were
removed here to reflect the real export path.
"""
from collections import defaultdict


def scan(read_conn, sample_id):
    """Return (buckets_dict, javaria_rows).

    javaria_rows is a list of (place_id, name, business_category_id,
    chain_id, has_visits) for the "outside + has visits" subset — the
    POIs the operator should either re-categorize (canonical fix) or
    explicitly accept as true sub-places.
    """
    with read_conn.cursor() as c:
        c.execute("SET statement_timeout=300000")
        c.execute("""
            SELECT p.id, p.name, p.business_category_id, p.chain_id,
                   b.business_category_ids,
                   (p.estimated_visits_monthly IS NOT NULL) AS has_visits
            FROM sample_places sp
            JOIN places p ON p.id = sp.place_id
            JOIN brands b ON b.key = p.chain_id
            WHERE sp.sample_id = %s
        """, (sample_id,))
        rows = c.fetchall()

    buckets = {
        "in_business_cats": 0,
        "outside": 0,
        "outside_with_visits": 0,
        "total_chained": len(rows),
    }
    javaria = []
    for pid, name, cat, chain, bc, has_visits in rows:
        bc = bc or []
        if cat in bc:
            buckets["in_business_cats"] += 1
        else:
            buckets["outside"] += 1
            if has_visits:
                buckets["outside_with_visits"] += 1
                javaria.append((pid, name, cat, chain, has_visits))

    return buckets, javaria


def rollup_by_chain(javaria_rows):
    """Group the Javaria set by chain_id. Returns dict[chain -> count]."""
    out = defaultdict(int)
    for pid, name, cat, chain, hv in javaria_rows:
        out[chain] += 1
    return dict(out)


def rollup_by_category(javaria_rows):
    """Group the Javaria set by business_category_id."""
    out = defaultdict(int)
    for pid, name, cat, chain, hv in javaria_rows:
        out[cat] += 1
    return dict(out)
