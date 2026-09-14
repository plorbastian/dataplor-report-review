"""DB (sample_places JOIN places on places_read_metal) vs the delivered
place_export CSV. The two must agree on:

  - row count (sample_places count == CSV row count)
  - the UUIDs (every places.uuid for the sample present in the CSV)
  - chain coverage (COUNT(chain_id IS NOT NULL) matches)
  - zero merged children (no CSV row's place has parent_id set)
"""
import csv
import gzip
import psycopg2.extras
import uuid as _uuidmod

psycopg2.extras.register_uuid()


def load_export_uuids(csv_gz_path, uuid_col="dataplor_id"):
    csv.field_size_limit(50 * 1024 * 1024)
    with gzip.open(csv_gz_path, "rt", encoding="utf-8") as f:
        return [row[uuid_col] for row in csv.DictReader(f) if row.get(uuid_col)]


def resolve_uuids(read_conn, uuids, chunk=5000):
    """Return dict[uuid_str -> place_id]."""
    out = {}
    for i in range(0, len(uuids), chunk):
        batch = [_uuidmod.UUID(x) for x in uuids[i:i + chunk]]
        with read_conn.cursor() as c:
            c.execute("SET statement_timeout=300000")
            c.execute("SELECT uuid::text, id FROM places WHERE uuid = ANY(%s)", (batch,))
            for u, pid in c.fetchall():
                out[u] = pid
    return out


def compare(read_conn, prod_conn, sample_id, csv_gz_path):
    """Return a dict summarizing the diff between DB and export."""
    csv_uuids = load_export_uuids(csv_gz_path)
    uuid_to_id = resolve_uuids(read_conn, csv_uuids)
    csv_ids = set(uuid_to_id.values())

    with read_conn.cursor() as c:
        c.execute("SELECT place_id FROM sample_places WHERE sample_id=%s", (sample_id,))
        sp_ids = {r[0] for r in c.fetchall()}

    with prod_conn.cursor() as c:
        c.execute("SELECT COUNT(*) FROM places WHERE id = ANY(%s) AND parent_id IS NOT NULL",
                  (list(csv_ids),))
        leaked_children = c.fetchone()[0]

    with read_conn.cursor() as c:
        c.execute("""SELECT COUNT(*) FROM sample_places sp JOIN places p ON p.id=sp.place_id
                     WHERE sp.sample_id=%s AND p.chain_id IS NOT NULL""", (sample_id,))
        db_chained = c.fetchone()[0]

    return {
        "sample_id": sample_id,
        "csv_rows": len(csv_uuids),
        "csv_unique_ids": len(csv_ids),
        "sample_places_rows": len(sp_ids),
        "in_csv_not_in_sp": len(csv_ids - sp_ids),
        "in_sp_not_in_csv": len(sp_ids - csv_ids),
        "unresolvable_uuids": len(csv_uuids) - len(uuid_to_id),
        "leaked_children_in_csv": leaked_children,
        "db_chained": db_chained,
    }
