"""Scan a sample for the Javaria pattern: chained POI whose
business_category_id is NOT in the brand's core_1_category_ids or
core_2_category_ids, and which HAS visits populated in the DB.

Those visits will be silently stripped when the place_export runs.

Bucket every chained POI in the sample by category-match against
its brand:

  in_core_1              — cat in brands.core_1_category_ids
  in_core_2              — cat in brands.core_2_category_ids
  in_business_cats_only  — cat in brands.business_category_ids (broader)
  outside_all            — cat not in any of the above
      → subset "outside_with_visits" is the Javaria set: the client
        will get the POI in the delivered CSV but without any visits.

Rows with no chain_id are excluded — the strip only fires on chained POIs.
"""
from collections import defaultdict


def scan(read_conn, sample_id):
    """Return (buckets_dict, javaria_rows).

    javaria_rows is a list of (place_id, name, business_category_id,
    chain_id, has_visits) for the "outside + has visits" subset.
    """
    with read_conn.cursor() as c:
        c.execute("SET statement_timeout=300000")
        c.execute("""
            SELECT p.id, p.name, p.business_category_id, p.chain_id,
                   b.core_1_category_ids, b.core_2_category_ids,
                   b.business_category_ids,
                   (p.estimated_visits_monthly IS NOT NULL) AS has_visits
            FROM sample_places sp
            JOIN places p ON p.id = sp.place_id
            JOIN brands b ON b.key = p.chain_id
            WHERE sp.sample_id = %s
        """, (sample_id,))
        rows = c.fetchall()

    buckets = {
        "in_core_1": 0,
        "in_core_2": 0,
        "in_business_cats_only": 0,
        "outside_all": 0,
        "outside_with_visits": 0,
        "total_chained": len(rows),
    }
    javaria = []
    for pid, name, cat, chain, c1, c2, bc, has_visits in rows:
        c1 = c1 or []
        c2 = c2 or []
        bc = bc or []
        if cat in c1:
            buckets["in_core_1"] += 1
        elif cat in c2:
            buckets["in_core_2"] += 1
        elif cat in bc:
            buckets["in_business_cats_only"] += 1
        else:
            buckets["outside_all"] += 1
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
