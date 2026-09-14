"""Phase 5 — delete merged children from sample_places.

After `matches:process` completes, every child row (`places.parent_id IS NOT NULL`)
that lives in `sample_places` for the affected sample must be removed. Otherwise
the next `place_export` job delivers a CSV that includes both parent and child,
which the client already saw as duplicates in the sample.

Rule (from operator experience):
  - Wait for the container task to reach `platform_task_completed_at`.
  - Then delete from `sample_places` using the `prod` role
    (`places_read_metal` is read-only).
  - Verify zero remaining children in the sample.
"""

DELETE_SQL = """
DELETE FROM sample_places sp
USING places p
WHERE p.id = sp.place_id
  AND sp.sample_id = %s
  AND p.parent_id IS NOT NULL;
"""

VERIFY_SQL = """
SELECT COUNT(*)
FROM sample_places sp
JOIN places p ON p.id = sp.place_id
WHERE sp.sample_id = %s
  AND p.parent_id IS NOT NULL;
"""


def delete_merged_children(prod_conn, sample_id, statement_timeout_ms=60_000):
    """Run the DELETE using the prod role. Returns rowcount."""
    with prod_conn.cursor() as c:
        c.execute(f"SET statement_timeout = {int(statement_timeout_ms)}")
        c.execute(DELETE_SQL, (sample_id,))
        deleted = c.rowcount
    prod_conn.commit()
    return deleted


def verify_no_children_left(prod_conn, sample_id):
    """Returns True if sample_places has no remaining rows whose place has
    a non-null parent_id for this sample."""
    with prod_conn.cursor() as c:
        c.execute(VERIFY_SQL, (sample_id,))
        (n,) = c.fetchone()
    return n == 0, n
