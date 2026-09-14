"""Post-delivery QA: run the checks directly against a delivered
place_export CSV instead of the DB view.

Why this matters: the DB view (`sample_places JOIN places`) sometimes
diverges from what the export emits — the CSV can round coordinates,
strip fields, or use the customer-facing UUID (`dataplor_id`) instead
of the internal `place_id`. Running QA against the delivered file is
the only way to catch what the client will actually see.

Usage:
    from dataplor_report_review.export_qa.from_csv import load_export
    rows = load_export("export_9990.csv.gz")
    # rows: list of dicts, one per POI, keyed by the CSV columns
    # + 'internal_id' filled in via a DB lookup on `places.uuid`.

Then pass `rows` to `components.cluster_same_name` and `name_scan.*`
below.
"""
import csv
import gzip
from typing import Iterable

import psycopg2.extras
import uuid as _uuidmod

psycopg2.extras.register_uuid()


UUID_COL = "dataplor_id"


def load_export(csv_gz_path, delimiter=","):
    """Stream a place_export .csv.gz into a list of dicts."""
    csv.field_size_limit(50 * 1024 * 1024)
    with gzip.open(csv_gz_path, "rt", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter=delimiter))


def resolve_internal_ids(rows, read_conn, chunk=5000, uuid_col=UUID_COL):
    """Fill each row's `internal_id` from `places.uuid` in places_read.
    Returns the same rows, mutated in place; rows whose UUID couldn't
    be resolved get `internal_id = None`.
    """
    uuids = list({r[uuid_col] for r in rows if r.get(uuid_col)})
    uuid_to_id = {}
    for i in range(0, len(uuids), chunk):
        batch = [_uuidmod.UUID(x) for x in uuids[i:i + chunk]]
        with read_conn.cursor() as c:
            c.execute("SET statement_timeout=300000")
            c.execute("SELECT uuid::text, id FROM places WHERE uuid = ANY(%s)",
                      (batch,))
            for u, pid in c.fetchall():
                uuid_to_id[u] = pid
    for r in rows:
        r["internal_id"] = uuid_to_id.get(r.get(uuid_col))
    return rows


PLACEHOLDER_TERMS_DEFAULT = frozenset({
    "makati", "makati city", "manila", "philippines", "ph",
    "metro manila", "room", "suite", "unit", "piso", "floor", "block",
})


def scan_placeholder_names(rows, terms=PLACEHOLDER_TERMS_DEFAULT, name_col="name"):
    """Return rows whose `name` (case-insensitive, stripped) matches a placeholder."""
    return [r for r in rows
            if (r.get(name_col) or "").strip().lower() in terms]


def scan_name_as_address(rows, name_col="name", addr_col="address",
                         digit_prefix_only=True):
    """Return rows where the name is a leading substring of the address.
    Catches both `name = address` and `name = address prefix` cases.

    IMPORTANT: many legitimate business names are ALSO leading substrings
    of their own address ("La Fuerza Plaza" at "La Fuerza Plaza, 2241
    Chino Roces Ave" — the plaza's real name is literally its address
    prefix). If you delete every row that matches, you drop 130+ legit
    buildings, malls, condos, and hotels.

    Default `digit_prefix_only=True` narrows to names that begin with a
    digit ("2284 Cervera", "5865 Zobel Roxas", "3016C Estrella") —
    those are almost always the address string being used as the name
    because ingestion had no real business name to record. Legit
    business names starting with a digit are rare and easy to confirm
    per-POI with the LLM.

    Set `digit_prefix_only=False` to widen to all substring matches and
    let the LLM decide each candidate.
    """
    out = []
    for r in rows:
        n = (r.get(name_col) or "").strip()
        a = (r.get(addr_col) or "").strip()
        if not n or not a or len(n) < 3:
            continue
        if not (n == a or a.lower().startswith(n.lower() + ",")
                or a.lower().startswith(n.lower() + " ")):
            continue
        if digit_prefix_only and not n[0].isdigit():
            continue
        out.append(r)
    return out


def rows_for_clustering(rows, id_key="internal_id"):
    """Adapt export rows for `components.cluster_same_name`, exposing
    the fields it needs: id, name, latitude, longitude, category."""
    out = []
    for r in rows:
        pid = r.get(id_key)
        if pid is None:
            continue
        try:
            lat = float(r.get("latitude") or 0)
            lng = float(r.get("longitude") or 0)
        except (TypeError, ValueError):
            continue
        out.append({
            "id": pid,
            "name": r.get("name") or "",
            "latitude": lat,
            "longitude": lng,
            "category": r.get("business_category") or "",
            "_raw": r,
        })
    return out
