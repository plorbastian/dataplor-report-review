"""Retrieval-gap check — catches POIs that Kuebiko's `bran_disco` job
silently excluded from the raw candidate pool.

The Kuebiko chainlink retrieval scores POIs by string similarity against
the canonical brand name and drops anything below its internal threshold.
It does NOT combine similarity with other strong signals (official brand
website, brand-prefixed name), so real stores with names like
`"BARA Puerta Real"`, `"Bara Cartagena (52JEE)"` or `"Super Bara <colonia>"`
never enter `raw.csv.gz` — even when they carry the brand's own website
and sit inside the brand's category family. The 2026-09-24 Tiendas Bara
incident is the canonical example: 162 of 171 valid stores we tagged that
day were NOT in Kuebiko's raw — recovered only by cross-referencing
FEMSA's own store locator KML pin by pin.

This module is the safety net between the report and the review. Given
the brand's website root + name (+ optional aliases), it surfaces POIs
that the retrieval should have brought but didn't, so the operator can
decide whether to tag them (or feed them to a targeted Omni run) before
closing the audit.

It does NOT fix Kuebiko — that fix lives in the backend `bran_disco`
retrieval SQL, adding an OR clause so a POI whose `website` matches the
brand's `website_root` or whose `name` starts with a brand alias enters
the pool regardless of similarity score. Reporting the gap here is what
makes that fix visible.

Public surface:

    load_kuebiko_raw(raw_path)           — read raw.csv.gz -> set of place_ids
    find_domain_orphans(conn, ...)       — POIs with brand website, untagged
    find_name_prefix_orphans(conn, ...)  — POIs starting with brand token, untagged
    cross_check_official_pins(conn, ...) — official-locator pins with no near tag
    retrieval_gap_report(conn, ...)      — all three above, deduped, CSV-friendly

Rows are described as `{"place_id", "name", "website", "chain_id",
"evidence", "why"}` where `evidence` is one of `domain`, `name_prefix`,
`locator_pin`, and `why` is a short human-readable justification.
"""
import csv
import gzip
import math


DEFAULT_LOCATOR_RADIUS_M = 100
DEFAULT_MIN_ALIAS_LENGTH = 4  # avoid `3B`/`Bara` matching random 3-4 char tokens


def load_kuebiko_raw(raw_path):
    """Read `raw.csv.gz` produced by Kuebiko's bran_disco job. Returns the
    set of `place_id` (str) values present in it.

    The retrieval gap is defined relative to this set: any POI meeting the
    brand's own signals (website match, name prefix, official-locator pin
    proximity) that is NOT in this set has been excluded upstream and is a
    candidate for recovery.
    """
    seen = set()
    with gzip.open(raw_path, "rt", encoding="utf-8", errors="ignore") as f:
        reader = csv.reader(f)
        next(reader, None)  # header
        for row in reader:
            if row and row[0]:
                seen.add(row[0])
    return seen


def _norm_domain(url):
    """Reduce a URL to a bare domain for substring comparison.

    ``"http://www.bara.com.mx/tiendas"`` -> ``"bara.com.mx"``.
    Empty or non-URL input returns an empty string.
    """
    s = (url or "").lower().strip()
    if not s:
        return ""
    for prefix in ("https://", "http://", "//"):
        if s.startswith(prefix):
            s = s[len(prefix):]
    if s.startswith("www."):
        s = s[4:]
    return s.split("/", 1)[0]


def find_domain_orphans(conn, brand_key, country_code, website_root,
                        kuebiko_raw_ids=None):
    """POIs whose website contains the brand's `website_root` but whose
    `chain_id` is not this brand (`None` or a different chain).

    A POI carrying `bara.com.mx` is almost never a mis-attribution — the
    brand owns that domain. Kuebiko excluding it is a retrieval-side
    scoring miss, not a semantic ambiguity.

    Args:
        conn: psycopg2 connection to `places` read replica.
        brand_key: chain_id string of the audited brand (e.g. `tiendas_bara`).
        country_code: ISO-2 lowercase (e.g. `mx`).
        website_root: bare-domain form, e.g. `bara.com.mx` (no scheme).
        kuebiko_raw_ids: optional set of place_ids present in raw.csv.gz.
            When provided, results are limited to POIs NOT in the raw
            (true retrieval gaps). When omitted, returns every untagged
            domain hit regardless of raw membership.

    Yields dicts described in the module docstring.
    """
    if not website_root:
        return
    root = _norm_domain(website_root) or website_root.lower()
    with conn.cursor() as c:
        c.execute("""
            SELECT id, name, website, chain_id
              FROM places
             WHERE country_code = %s
               AND parent_id IS NULL
               AND website ILIKE %s
               AND (chain_id IS NULL OR chain_id <> %s)
        """, (country_code, f"%{root}%", brand_key))
        for pid, name, website, chain in c.fetchall():
            if kuebiko_raw_ids is not None and str(pid) in kuebiko_raw_ids:
                continue
            yield {
                "place_id": pid, "name": name or "", "website": website or "",
                "chain_id": chain,
                "evidence": "domain",
                "why": (
                    f"website contains brand's official domain {root!r}; "
                    f"currently chain_id={chain!r}, no upstream candidate in raw"
                ),
            }


def find_name_prefix_orphans(conn, brand_key, country_code, aliases,
                             kuebiko_raw_ids=None,
                             min_alias_length=DEFAULT_MIN_ALIAS_LENGTH):
    """POIs whose name starts with any of the brand's `aliases` but whose
    `chain_id` is not this brand.

    Aliases must be at least `min_alias_length` characters (default 4) to
    avoid false positives on short tokens like `3B` (which would match
    `3B Consulting`). The brand's canonical name and every documented
    synonym / rebrand variant are appropriate inputs; short abbreviations
    should be validated with an extra source (domain match, category).

    Args:
        conn: psycopg2 connection.
        brand_key: chain_id string.
        country_code: ISO-2 lowercase.
        aliases: iterable of brand name strings (canonical + any variants).
        kuebiko_raw_ids: same semantics as `find_domain_orphans`.
        min_alias_length: minimum character count for an alias to be used.

    Yields dicts described in the module docstring.
    """
    for alias in aliases:
        a = (alias or "").strip()
        if len(a) < min_alias_length:
            continue
        with conn.cursor() as c:
            # ILIKE 'alias%' uses the btree_prefix index cheaply; anchored
            # so we do not match `"Casa Alias 3"` etc.
            c.execute("""
                SELECT id, name, website, chain_id
                  FROM places
                 WHERE country_code = %s
                   AND parent_id IS NULL
                   AND name ILIKE %s
                   AND (chain_id IS NULL OR chain_id <> %s)
            """, (country_code, f"{a}%", brand_key))
            for pid, name, website, chain in c.fetchall():
                if kuebiko_raw_ids is not None and str(pid) in kuebiko_raw_ids:
                    continue
                yield {
                    "place_id": pid, "name": name or "", "website": website or "",
                    "chain_id": chain,
                    "evidence": "name_prefix",
                    "why": (
                        f"name starts with brand alias {a!r}; "
                        f"currently chain_id={chain!r}, no upstream candidate in raw"
                    ),
                }


def _haversine_m(lat1, lng1, lat2, lng2):
    """Metres between two lat/lng points."""
    r = 6371000.0
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlng = math.radians(lng2 - lng1)
    a = (math.sin(dlat / 2) ** 2
         + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlng / 2) ** 2)
    return r * 2 * math.asin(math.sqrt(a))


def cross_check_official_pins(conn, brand_key, country_code, pins,
                              radius_m=DEFAULT_LOCATOR_RADIUS_M):
    """Given a list of official-locator pins `[{"lat", "lng", "name"}]`
    from the brand's own website / KML export, yield rows for each pin
    where the nearest DB POI within `radius_m` is NOT tagged as this brand.

    Pins with a POI already tagged as `brand_key` within radius are
    considered satisfied and are skipped. Pins with no POI at all inside
    the radius yield an empty `place_id` — those are candidates for a
    provisional-add (or an Omni scrape) but cannot be tagged inline.

    Args:
        conn: psycopg2 connection.
        brand_key: chain_id string.
        country_code: ISO-2 lowercase.
        pins: iterable of {"lat": float, "lng": float, "name": str}.
        radius_m: match radius. 100m is the default from the Bara
            reconciliation on 2026-09-24 — trades recall for precision.

    Yields dicts described in the module docstring, with an extra
    `distance_m` on locator-pin evidence and possibly `place_id=None`.
    """
    for pin in pins:
        lat = float(pin["lat"]); lng = float(pin["lng"])
        with conn.cursor() as c:
            # bbox first (uses GIST), then geography ST_DWithin
            c.execute("""
                SELECT id, name, website, chain_id,
                       ST_Distance(coordinates::geography,
                                   ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography)::int AS d
                  FROM places
                 WHERE country_code = %s
                   AND parent_id IS NULL
                   AND coordinates && ST_Expand(
                       ST_SetSRID(ST_MakePoint(%s,%s),4326)::geometry, 0.003)
                   AND ST_DWithin(coordinates::geography,
                       ST_SetSRID(ST_MakePoint(%s,%s),4326)::geography, %s)
                 ORDER BY coordinates <-> ST_SetSRID(ST_MakePoint(%s,%s),4326)
                 LIMIT 1
            """, (lng, lat, country_code, lng, lat, lng, lat, radius_m, lng, lat))
            row = c.fetchone()
        if row is None:
            yield {
                "place_id": None,
                "name": pin.get("name") or "",
                "website": "", "chain_id": None,
                "distance_m": None,
                "evidence": "locator_pin",
                "why": (
                    f"official-locator pin {pin.get('name')!r} has no POI "
                    f"in DB within {radius_m}m — candidate for provisional-add"
                ),
            }
            continue
        pid, name, website, chain, dist = row
        if chain == brand_key:
            continue  # already tagged, no gap
        yield {
            "place_id": pid, "name": name or "", "website": website or "",
            "chain_id": chain,
            "distance_m": int(dist) if dist is not None else None,
            "evidence": "locator_pin",
            "why": (
                f"official-locator pin {pin.get('name')!r} matched DB POI "
                f"{name!r} at {dist}m; currently chain_id={chain!r}"
            ),
        }


def retrieval_gap_report(conn, brand_key, country_code, *,
                         website_root=None,
                         aliases=(),
                         official_pins=None,
                         kuebiko_raw_ids=None,
                         radius_m=DEFAULT_LOCATOR_RADIUS_M):
    """Run all three checks, dedupe by `place_id`, and return the sorted
    findings list plus a short summary dict.

    Findings with the same `place_id` from multiple evidence sources are
    merged — the merged row lists every evidence type in `evidence`
    (comma-joined) and concatenates the `why` fields. Findings without a
    `place_id` (locator pins with no DB match) are kept as separate rows.

    Args:
        conn: psycopg2 connection.
        brand_key: chain_id string.
        country_code: ISO-2 lowercase.
        website_root: brand's official domain (bare, no scheme).
        aliases: iterable of brand name strings.
        official_pins: iterable of `{"lat", "lng", "name"}` pins.
        kuebiko_raw_ids: set from `load_kuebiko_raw` (optional).
        radius_m: for `cross_check_official_pins`.

    Returns:
        (findings, summary) where
          findings = list of dicts, sorted by place_id (nones last);
          summary  = {"total", "by_evidence", "no_place_id"}.
    """
    per_pid = {}
    no_pid = []

    def _absorb(row):
        pid = row.get("place_id")
        if pid is None:
            no_pid.append(row); return
        existing = per_pid.get(pid)
        if existing is None:
            per_pid[pid] = dict(row); return
        # merge evidence + why
        ev = set(existing["evidence"].split(",")) | {row["evidence"]}
        existing["evidence"] = ",".join(sorted(ev))
        existing["why"] = "; ".join(
            filter(None, [existing.get("why"), row.get("why")])
        )

    if website_root:
        for row in find_domain_orphans(
            conn, brand_key, country_code, website_root, kuebiko_raw_ids
        ):
            _absorb(row)
    if aliases:
        for row in find_name_prefix_orphans(
            conn, brand_key, country_code, aliases, kuebiko_raw_ids
        ):
            _absorb(row)
    if official_pins:
        for row in cross_check_official_pins(
            conn, brand_key, country_code, official_pins, radius_m
        ):
            _absorb(row)

    findings = sorted(per_pid.values(), key=lambda r: r["place_id"]) + no_pid
    by_ev = {}
    for r in findings:
        for e in r["evidence"].split(","):
            by_ev[e] = by_ev.get(e, 0) + 1
    summary = {
        "total": len(findings),
        "by_evidence": by_ev,
        "no_place_id": len(no_pid),
    }
    return findings, summary


def write_findings_csv(findings, out_path):
    """Persist a findings list to `out_path` as a review-ready CSV.

    Columns: place_id, name, website, chain_id, evidence, distance_m, why.
    """
    fields = ["place_id", "name", "website", "chain_id",
              "evidence", "distance_m", "why"]
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in findings:
            w.writerow(r)
