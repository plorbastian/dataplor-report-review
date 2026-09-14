"""Phase 2a — enrich each actionable pair with full place context from the DB.

Pulls both places for every pair from `places_read_metal`:
    id, name, chain_id, business_category_id, address, city, state,
    latitude, longitude, website, phone, parent_id, provisional,
    location_parent_id, external_ids

`external_ids` is where the Chase-ATM distinguishability signals live:
    google_places_id  — different gpids at same coord = distinct POIs
    yext_source       — different yext sources = distinct
    url_slug          — different location paths = distinct
"""
import csv

REQUIRED_COLS = (
    "id, name, chain_id, business_category_id, address, city, state, "
    "latitude::float, longitude::float, website, phone, parent_id, provisional, "
    "location_parent_id, external_ids"
)


def _ext_get(ext, key):
    if isinstance(ext, dict):
        return ext.get(key, "") or ""
    return ""


def load_pairs(csv_path):
    """Load the actionable pairs CSV emitted by Phase 1."""
    csv.field_size_limit(50 * 1024 * 1024)
    return list(csv.DictReader(open(csv_path, encoding="utf-8")))


def distinct_place_ids(pairs):
    ids = set()
    for r in pairs:
        ids.add(int(r["place1_id"]))
        ids.add(int(r["place2_id"]))
    return list(ids)


def pull_places(conn, place_ids, chunk=5000):
    """Return dict[place_id -> place_context]. `conn` is a psycopg2 connection
    to places_read_metal (or any replica of the places table).
    """
    out = {}
    for i in range(0, len(place_ids), chunk):
        batch = place_ids[i:i + chunk]
        with conn.cursor() as c:
            c.execute(
                f"SELECT {REQUIRED_COLS} FROM places WHERE id IN %s",
                (tuple(batch),),
            )
            for row in c.fetchall():
                ext = row[14] or {}
                out[row[0]] = {
                    "id": row[0],
                    "name": row[1] or "",
                    "chain": row[2],
                    "category": row[3],
                    "address": row[4] or "",
                    "city": row[5],
                    "state": row[6],
                    "lat": row[7],
                    "lng": row[8],
                    "website": row[9] or "",
                    "phone": row[10] or "",
                    "parent": row[11],
                    "provisional": row[12],
                    "loc_parent": row[13],
                    "gpid": _ext_get(ext, "google_places_id"),
                    "y_source": _ext_get(ext, "yext_source"),
                    "url_slug": _ext_get(ext, "url_slug"),
                    "ext": ext if isinstance(ext, dict) else {},
                }
    return out
