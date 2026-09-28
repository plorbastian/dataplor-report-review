"""Load brand context needed to review a brand-heavy sample.

For each `chain_id` in the sample we need:

  - `business_category_ids` — the set of category keys the brand
    considers "its own". A place is `is_core=true` (visits preserved
    at export, visible on platform) iff its `business_category_id`
    is in this list.
  - domain(s) from `brand_websites`  — the brand's official domain(s),
    used both as a positive signal ("website contains the brand's own
    domain") and to disambiguate from same-name competitor brands.
  - name variants from `brand_names` — used to score how well a POI
    name anchors to the brand, e.g. 'Tienda Bara' vs 'Tiendas Bara'.

Every category key referenced from `business_category_ids` MUST exist
in the `business_categories` taxonomy table. `load_brand_context`
enforces this by default — it queries the taxonomy and raises
`InvalidCategoryError` if any brand carries a category key that does
not resolve. This prevents silent typo-drift like `supermarcet` or a
category deprecated upstream from being accepted at review time and
quietly excluding real POIs from the sample.

Historical note: an earlier revision of this loader also read
`core_1_category_ids` and `core_2_category_ids`. Those columns exist
on `brands` but are unused stale metadata — confirmed by their author
in September 2026 — and were removed here so the module reflects only
signals that actually drive the export path.

The returned structure is fed to `review.review_pois()` verbatim.
"""


class InvalidCategoryError(ValueError):
    """Raised by `load_brand_context` when a brand's `business_category_ids`
    contains a key that is not present in `business_categories.key`.

    The exception carries `.invalid` — a dict mapping
    `chain_id -> [bad keys]` — listing exactly which keys per brand
    failed the check. That lets a caller either fix the brand
    metadata (correct typo, add the missing key to the taxonomy) or
    explicitly bypass with `validate_categories=False` for a
    diagnostic run.
    """

    def __init__(self, message, invalid):
        super().__init__(message)
        self.invalid = invalid


def _load_valid_category_keys(conn):
    """Return the set of `business_categories.key` values known upstream.

    Uses `SELECT DISTINCT key` — the table has one row per taxonomy key.
    """
    with conn.cursor() as c:
        c.execute("SELECT key FROM business_categories")
        return {row[0] for row in c.fetchall() if row[0]}


def load_brand_context(conn, chain_ids, *, validate_categories=True):
    """Return dict[chain_id -> brand_ctx].

    brand_ctx keys:
      name           — human-readable brand name from `brands.name`
      business_cats  — list[str] of category keys from
                       `brands.business_category_ids`
      domains        — list[str] of bare-domain forms from `brand_websites`
      names          — list[str] of name variants from `brand_names`

    Missing brands come back absent from the dict (silent). Callers
    should handle that — a POI with a `chain_id` that has no brand row
    is a data-integrity problem the review can flag as UNCLEAR.
    """
    if not chain_ids:
        return {}
    keys = tuple(chain_ids)
    with conn.cursor() as c:
        c.execute("""
            SELECT
                b.id, b.key, b.name,
                b.business_category_ids
            FROM brands b
            WHERE b.key IN %s
        """, (keys,))
        brand_rows = c.fetchall()

        by_id = {r[0]: r for r in brand_rows}
        brand_ids = tuple(by_id.keys()) or (0,)

        c.execute("""
            SELECT brand_id, domain
              FROM brand_websites
             WHERE brand_id IN %s
        """, (brand_ids,))
        domains_by_brand = {}
        for bid, dom in c.fetchall():
            domains_by_brand.setdefault(bid, []).append(dom)

        c.execute("""
            SELECT brand_id, name
              FROM brand_names
             WHERE brand_id IN %s
        """, (brand_ids,))
        names_by_brand = {}
        for bid, nm in c.fetchall():
            names_by_brand.setdefault(bid, []).append(nm)

    out = {}
    for bid, key, name, bc in brand_rows:
        out[key] = {
            "name": name,
            "business_cats": list(bc or []),
            "domains": domains_by_brand.get(bid, []),
            "names": names_by_brand.get(bid, []),
        }

    if validate_categories and out:
        valid_keys = _load_valid_category_keys(conn)
        invalid = {}
        for chain_key, ctx in out.items():
            bad = [k for k in ctx.get("business_cats", []) if k not in valid_keys]
            if bad:
                invalid[chain_key] = bad
        if invalid:
            preview = "; ".join(
                f"{ck}: {ks}" for ck, ks in invalid.items()
            )
            raise InvalidCategoryError(
                "Brand business_category_ids keys not present in "
                f"business_categories taxonomy: {preview}",
                invalid,
            )

    return out


def load_sample_pois(conn, sample_id):
    """Return the list of dicts the review consumes, one per POI in
    `sample_places` for `sample_id`.

    Fields carry through directly from `places`: id, name, chain_id
    (chain), business_category_id (cat), address, website, provisional,
    popularity_score, lat, lng, external_ids (ext), has_visits.
    """
    with conn.cursor() as c:
        c.execute("""
            SELECT p.id, p.name, p.chain_id, p.business_category_id,
                   p.address, p.website,
                   p.provisional, p.popularity_score,
                   ST_Y(p.coordinates::geometry) AS lat,
                   ST_X(p.coordinates::geometry) AS lng,
                   p.external_ids,
                   p.estimated_visits_monthly IS NOT NULL AS has_visits
              FROM sample_places sp
              JOIN places p ON p.id = sp.place_id
             WHERE sp.sample_id = %s
             ORDER BY p.chain_id, p.id
        """, (sample_id,))
        rows = c.fetchall()

    out = []
    for r in rows:
        out.append({
            "id": r[0], "name": r[1] or "", "chain": r[2],
            "cat": r[3] or "", "address": r[4] or "",
            "website": (r[5] or "").lower(),
            "provisional": r[6], "pop": float(r[7] or 0),
            "lat": r[8], "lng": r[9],
            "ext": r[10] or {}, "has_visits": r[11],
        })
    return out
