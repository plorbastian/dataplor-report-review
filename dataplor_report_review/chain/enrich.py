"""Chain enrichment — pull brand context + POI context needed for LLM review."""


PLACE_COLUMNS = (
    "id, name, chain_id, business_category_id, address, city, state, country, "
    "latitude::float, longitude::float, website, phone, provisional, external_ids"
)


BRAND_COLUMNS = (
    "id, name, country_code, primary_category, allowed_categories, "
    "banned_categories, aliases, website_root"
)


def pull_places(conn, place_ids, chunk=5000):
    """Return dict[place_id -> place context]."""
    out = {}
    for i in range(0, len(place_ids), chunk):
        batch = place_ids[i:i + chunk]
        with conn.cursor() as c:
            c.execute(f"SELECT {PLACE_COLUMNS} FROM places WHERE id IN %s", (tuple(batch),))
            for row in c.fetchall():
                out[row[0]] = {
                    "id": row[0], "name": row[1] or "", "chain": row[2],
                    "category": row[3], "address": row[4] or "",
                    "city": row[5], "state": row[6], "country": row[7],
                    "lat": row[8], "lng": row[9],
                    "website": row[10] or "", "phone": row[11] or "",
                    "provisional": row[12], "ext": row[13] or {},
                }
    return out


def pull_brands(conn, chain_ids):
    """Return dict[chain_id -> brand context]. `chain_id` is a string slug
    (e.g. "chase_bank"), stored on the brand row."""
    if not chain_ids:
        return {}
    with conn.cursor() as c:
        c.execute(f"SELECT {BRAND_COLUMNS} FROM brands WHERE id IN %s",
                  (tuple(chain_ids),))
        out = {}
        for row in c.fetchall():
            out[row[0]] = {
                "id": row[0], "name": row[1], "country_code": row[2],
                "primary_category": row[3],
                "allowed_categories": row[4] or [],
                "banned_categories": row[5] or [],
                "aliases": row[6] or [], "website_root": row[7] or "",
            }
        return out
