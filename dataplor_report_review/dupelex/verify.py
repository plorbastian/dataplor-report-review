"""Phase 6 — verify end-state in prod + places_read after merges land.

Read replica (`places_read_metal`) lags prod by ~5 min. Running the
verification against both roles catches (a) merges that never wrote to prod
and (b) replication lag surprising a downstream consumer.

Checks:
  1. sample_places count in both roles matches.
  2. Zero rows in sample_places whose place has a non-null parent_id.
  3. Number of place_ids from the merge list that now have parent_id set
     equals (or approaches) the child count from the merge components.
"""

SAMPLE_COUNT_SQL = "SELECT COUNT(*) FROM sample_places WHERE sample_id = %s"

DIRTY_CHILDREN_SQL = """
SELECT COUNT(*)
FROM sample_places sp
JOIN places p ON p.id = sp.place_id
WHERE sp.sample_id = %s
  AND p.parent_id IS NOT NULL;
"""

CHILDREN_WITH_PARENT_SQL = """
SELECT COUNT(*)
FROM places
WHERE id = ANY(%s)
  AND parent_id IS NOT NULL;
"""


def _count(conn, sql, args):
    with conn.cursor() as c:
        c.execute(sql, args)
        (n,) = c.fetchone()
    return n


def compare_sample_counts(prod_conn, read_conn, sample_id):
    """Return (prod_count, read_count)."""
    return (
        _count(prod_conn, SAMPLE_COUNT_SQL, (sample_id,)),
        _count(read_conn, SAMPLE_COUNT_SQL, (sample_id,)),
    )


def count_dirty_children(conn, sample_id):
    """Rows in sample_places whose place.parent_id is not null (shouldn't be > 0
    once Phase 5 has run)."""
    return _count(conn, DIRTY_CHILDREN_SQL, (sample_id,))


def count_children_realized(conn, place_ids):
    """Of a list of place_ids (typically the child side of each merge pair),
    how many now have parent_id set in the given role?"""
    return _count(conn, CHILDREN_WITH_PARENT_SQL, (list(place_ids),))


def full_check(prod_conn, read_conn, sample_id, expected_child_ids):
    """Consolidated verification. Returns a dict of counts."""
    prod_ct, read_ct = compare_sample_counts(prod_conn, read_conn, sample_id)
    return {
        "sample_id": sample_id,
        "sample_count_prod": prod_ct,
        "sample_count_read": read_ct,
        "sample_counts_match": prod_ct == read_ct,
        "dirty_children_prod": count_dirty_children(prod_conn, sample_id),
        "dirty_children_read": count_dirty_children(read_conn, sample_id),
        "children_realized_prod": count_children_realized(prod_conn, expected_child_ids),
        "children_realized_read": count_children_realized(read_conn, expected_child_ids),
        "expected_children": len(expected_child_ids),
    }
