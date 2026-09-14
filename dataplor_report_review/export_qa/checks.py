"""Export-side QA queries. Each function returns a list of anomaly rows.

Run these against `places_read_metal` — that's the replica the export
job reads from. Any row a check returns is a candidate for either
DELETE from sample_places (garbage) or MERGE via matches:process
(missed dupe). Pass through per-POI LLM judgment before acting.
"""
import math
from collections import defaultdict


def _hav(a, b):
    """Haversine meters between (lat,lng) tuples."""
    lat1, lng1 = a; lat2, lng2 = b
    R = 6371000
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def short_names(conn, sample_id, max_len=3):
    """Names of length <= max_len OR only digits/whitespace/punctuation.
    Returns list of (place_id, name, category, address, chain_id, website)."""
    with conn.cursor() as c:
        c.execute("""SELECT p.id, p.name, p.business_category_id, p.address, p.chain_id, p.website
                     FROM sample_places sp JOIN places p ON p.id=sp.place_id
                     WHERE sp.sample_id=%s
                       AND (LENGTH(TRIM(p.name)) <= %s
                            OR p.name ~ '^[0-9\\s]+$'
                            OR p.name ~ '^[[:punct:]\\s]+$')""",
                  (sample_id, max_len))
        return c.fetchall()


PLACEHOLDER_TERMS_DEFAULT = (
    "Makati", "Makati City", "Manila", "Philippines", "PH",
    "Metro Manila", "Room", "Suite", "Unit", "Piso", "Floor", "Block",
)


def placeholder_names(conn, sample_id, terms=PLACEHOLDER_TERMS_DEFAULT):
    """Names that literally equal a placeholder term (city name, unit label)."""
    like_clauses = " OR ".join(["TRIM(p.name) ILIKE %s" for _ in terms])
    with conn.cursor() as c:
        c.execute(f"""SELECT p.id, p.name, p.business_category_id, p.address,
                             p.chain_id, p.website
                      FROM sample_places sp JOIN places p ON p.id=sp.place_id
                      WHERE sp.sample_id=%s AND ({like_clauses})""",
                  (sample_id, *terms))
        return c.fetchall()


def name_equals_address(conn, sample_id):
    """Places where p.name literally equals OR is a leading substring of p.address.

    A strict equality check misses the common failure mode where a POI's
    name is stored as `"2284 Cervera"` while its address is
    `"2284 Cervera, Makati, 1230"` — same placeholder, different string.
    We catch both patterns and let the LLM decide per POI whether the
    name is a legitimate business identifier that happens to look like
    an address (rare) or a placeholder to remove (common).
    """
    with conn.cursor() as c:
        c.execute("""SELECT p.id, p.name, p.business_category_id, p.address
                     FROM sample_places sp JOIN places p ON p.id=sp.place_id
                     WHERE sp.sample_id=%s
                       AND p.name IS NOT NULL AND p.address IS NOT NULL
                       AND LENGTH(p.name) >= 3
                       AND (p.name = p.address
                            OR p.address ILIKE p.name || ',%%'
                            OR p.address ILIKE p.name || ' %%')""", (sample_id,))
        return c.fetchall()


PEOPLE_PROPERTY_CATS = (
    "hospital", "private_hospital", "general_practitioner", "lawyer",
    "psychiatrist", "condominium_complex", "condominium", "apartment_building",
    "apartment_complex", "housing_society", "church", "university",
    "place_of_worship",
)


def chain_cat_mismatch(conn, sample_id, cats=PEOPLE_PROPERTY_CATS):
    """chain_id set on categories where a chain rarely makes sense
    (people/property). Some rows will be legit (bank branch inside a
    condo building) — always confirm per-POI before acting."""
    with conn.cursor() as c:
        c.execute("""SELECT p.id, p.name, p.chain_id, p.business_category_id, p.address
                     FROM sample_places sp JOIN places p ON p.id=sp.place_id
                     WHERE sp.sample_id=%s AND p.chain_id IS NOT NULL
                       AND p.business_category_id IN %s""",
                  (sample_id, tuple(cats)))
        return c.fetchall()


def residual_name_dupes(conn, sample_id, max_meters=50, min_name_len=3,
                       skip_group_larger_than=30):
    """Same normalized name + Haversine < max_meters, missed by dupelex.
    Returns list of (id_a, id_b, name, distance_m, cat_a, cat_b, addr_a, addr_b).
    """
    with conn.cursor() as c:
        c.execute("""SELECT p.id, LOWER(TRIM(p.name)) AS n, p.name,
                            p.latitude::float, p.longitude::float,
                            p.business_category_id, p.address
                     FROM sample_places sp JOIN places p ON p.id=sp.place_id
                     WHERE sp.sample_id=%s AND p.name IS NOT NULL AND p.name<>''""",
                  (sample_id,))
        rows = c.fetchall()

    by_name = defaultdict(list)
    for r in rows:
        if len(r[1]) >= min_name_len:
            by_name[r[1]].append(r)

    out = []
    for _, group in by_name.items():
        if 2 <= len(group) <= skip_group_larger_than:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    d = _hav((a[3], a[4]), (b[3], b[4]))
                    if d < max_meters:
                        out.append((a[0], b[0], a[2], d, a[5], b[5], a[6], b[6]))
    return out


def geocode_centroid_pileup(conn, sample_id, min_pile=100):
    """POIs that share the SAME (lat, lng) — usually a geocode fell back
    to a bounding-box centroid instead of matching the address.

    On sample 9990 (Red Bull PH), the canonical-check surfaced 574 POIs
    pinned at the p99 lat/lon ceiling — the "default centroid" pattern.
    A run of the same coord across N POIs is the tell.
    """
    with conn.cursor() as c:
        c.execute("""
            SELECT ROUND(p.latitude::numeric, 5) AS lat, ROUND(p.longitude::numeric, 5) AS lng,
                   COUNT(*) AS n, ARRAY_AGG(p.id) AS place_ids
            FROM sample_places sp
            JOIN places p ON p.id = sp.place_id
            WHERE sp.sample_id = %s
              AND p.latitude IS NOT NULL
              AND p.longitude IS NOT NULL
            GROUP BY ROUND(p.latitude::numeric, 5), ROUND(p.longitude::numeric, 5)
            HAVING COUNT(*) >= %s
            ORDER BY COUNT(*) DESC
        """, (sample_id, min_pile))
        return c.fetchall()


def hours_2400_ambiguity(conn, sample_id):
    """POIs with 00:00 open + 00:00 close on any weekday — the encoding
    is ambiguous between "24 hours" and "closed that day".

    The canonical check on sample 9990 called this out as one of the
    top DQ items — ~4,000 rows per weekday show this pattern. Not all
    are 24/7 (some are genuinely-closed days); the delta between them
    is whether `additional_open_hours` carries a `24/7` marker.
    """
    with conn.cursor() as c:
        c.execute("""
            SELECT p.id, p.business_category_id, p.name,
                   p.monday_open, p.monday_close,
                   p.tuesday_open, p.tuesday_close,
                   p.wednesday_open, p.wednesday_close,
                   p.thursday_open, p.thursday_close,
                   p.friday_open, p.friday_close,
                   p.saturday_open, p.saturday_close,
                   p.sunday_open, p.sunday_close,
                   p.additional_open_hours
            FROM sample_places sp
            JOIN places p ON p.id = sp.place_id
            WHERE sp.sample_id = %s
              AND ((p.monday_open = '00:00' AND p.monday_close = '00:00')
                OR (p.tuesday_open = '00:00' AND p.tuesday_close = '00:00')
                OR (p.wednesday_open = '00:00' AND p.wednesday_close = '00:00')
                OR (p.thursday_open = '00:00' AND p.thursday_close = '00:00')
                OR (p.friday_open = '00:00' AND p.friday_close = '00:00')
                OR (p.saturday_open = '00:00' AND p.saturday_close = '00:00')
                OR (p.sunday_open = '00:00' AND p.sunday_close = '00:00'))
        """, (sample_id,))
        return c.fetchall()


def historical_scores_pre_opened(conn, sample_id, score_col="historical_popularity_scores"):
    """POIs with entries in `historical_popularity_scores` (or
    `historical_sentiment_scores`) for months earlier than
    `first_opened`.

    The underlying model back-fills newly-opened POIs from neighbours,
    so pre-open months reflect modelled traffic, not observed. The
    canonical check flags 2,400+ POIs on 9990. Fix: at delivery time
    either null the pre-open month keys or add a metadata flag to
    distinguish observed vs modelled months.
    """
    with conn.cursor() as c:
        c.execute(f"""
            SELECT p.id, p.name, p.first_opened,
                   (SELECT jsonb_object_agg(k, v)
                    FROM jsonb_each(p.{score_col})
                    WHERE k::date < p.first_opened::date) AS pre_open_entries
            FROM sample_places sp
            JOIN places p ON p.id = sp.place_id
            WHERE sp.sample_id = %s
              AND p.first_opened IS NOT NULL
              AND p.{score_col} IS NOT NULL
              AND EXISTS (
                  SELECT 1 FROM jsonb_object_keys(p.{score_col}) k
                  WHERE k::date < p.first_opened::date
              )
        """, (sample_id,))
        return c.fetchall()


def same_chain_close(conn, sample_id, max_meters=20, skip_group_larger_than=200):
    """Same chain_id + Haversine < max_meters. These are almost always
    dupes the dupelex report missed (score too low, or no strong signal).
    """
    with conn.cursor() as c:
        c.execute("""SELECT p.id, p.name, p.chain_id,
                            p.latitude::float, p.longitude::float
                     FROM sample_places sp JOIN places p ON p.id=sp.place_id
                     WHERE sp.sample_id=%s AND p.chain_id IS NOT NULL""",
                  (sample_id,))
        rows = c.fetchall()

    by_chain = defaultdict(list)
    for r in rows:
        by_chain[r[2]].append(r)

    out = []
    for chain, group in by_chain.items():
        if 2 <= len(group) <= skip_group_larger_than:
            for i in range(len(group)):
                for j in range(i + 1, len(group)):
                    a, b = group[i], group[j]
                    d = _hav((a[3], a[4]), (b[3], b[4]))
                    if d < max_meters:
                        out.append((a[0], b[0], chain, d, a[1], b[1]))
    return out
