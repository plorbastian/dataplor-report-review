# Methodology — post-cleanup export DQ

Third pillar of the review methodology. Runs AFTER dupelex + chain have landed and after Phase 5 sample_places cleanup. The DQ layer catches issues that the pair-based dupelex pipeline cannot see by construction:

1. **Garbage names** — POIs whose `name` is a city placeholder ("Makati", "Manila"), a room label ("Room 204"), or the address string itself ("9681 Kamagong"). These are places DataPlor's ingestion pulled from Google without a real business name. They clutter the client-facing export and read as bad data even though the underlying POI might be a real venue.

2. **Missed dupes** — pairs the dupelex report never emitted (score below threshold, no strong signal in the raw report) but which are obviously the same POI on inspection: same normalized name + <50m coords, or same `chain_id` + <20m coords.

## What the export sees

The client-facing `place_export` job reads:

```
sample_places (sample_id=X)
  JOIN places (places_read_metal)
```

Anything the export sees comes from that view. This QA layer runs the same join and evaluates each row.

## Checks

| Check | Query | What it catches |
|-------|-------|-----------------|
| `short_names` | `LENGTH(name) <= 3` OR digits/symbols only | Names like `"no"`, `"V!"`, `"Mj"` — some legit brands (K2, LG), most noise. Requires LLM per-POI. |
| `placeholder_names` | `name ILIKE 'Makati' / 'Manila' / 'Room' / 'Suite' / 'Unit' / ...` | POIs whose "name" is a city or unit label. Almost always garbage — DELETE from sample_places. |
| `name_equals_address` | `name = address` | POIs where the name field carries the address string. Almost always garbage — DELETE. |
| `chain_cat_mismatch` | chain_id set on `hospital` / `condominium_complex` / `church` / etc. | chain_id got attached to a container-type POI. Some legit (bank branch in a condo building), most FPs. Requires LLM per-POI. |
| `residual_name_dupes` | Same normalized name + Haversine <50m, missed by dupelex | Missed dupes. Group by name, pairwise within group. |
| `same_chain_close` | Same chain_id + Haversine <20m, missed by dupelex | Chain-verified missed dupes. Very high signal — near-zero FPs. |
| `geocode_centroid_pileup` | ≥100 POIs sharing the same (lat, lng) after rounding to 5 decimals | Geocode fell back to a bounding-box centroid instead of matching the address. On 9990 the canonical check flagged 574 POIs pinned to the p99 lat/lon. |
| `hours_2400_ambiguity` | POIs with 00:00 open + 00:00 close on any weekday | Encoding is ambiguous between "24 hours" and "closed that day" — the `additional_open_hours` `24/7` marker is the disambiguator. Sample 9990 had ~4,000/day rows in this state. |
| `historical_scores_pre_opened` | Entries in `historical_popularity_scores` / `historical_sentiment_scores` keyed to months before `first_opened` | The model back-fills new POIs from neighbours, so pre-open months are modelled, not observed. At delivery, null the pre-open month keys or add a metadata flag distinguishing observed vs modelled. On 9990: 2,476 POIs / 24,180 entries for popularity, 340 / 3,437 for sentiment. |
| `client_facing_garbage_names` | Names that will look bad in Excel regardless of technical validity — single-Latin-char (`V`, `Jm`), asterisk-wrapped run-ons, math-italic decoration, small-caps decoration, date-format-as-name (`11-Jul`), `@handle` prefix, quote-wrapped, parenthesized-code prefix (`(cmea)`), phone-country-code prefix (`+81 Bar`) | Excel-view garbage. **Do NOT** flag legitimate non-Latin script names (Hebrew, Arabic, Devanagari, Tamil, CJK, Thai) as garbage — Excel's poor RTL support makes them LOOK broken but the underlying data is fine. On 9990: 32 rows caught by the patterns above, all legit garbage; ~250 CJK/RTL rows preserved as valid businesses. |

## Run against the DELIVERED CSV, not just the DB view

The DB view (`sample_places JOIN places`) is a proxy for what the export delivers, but it is not the same thing. The export flattens fields, uses the customer-facing `dataplor_id` UUID instead of internal `place_id`, and can round coordinates. On sample 9990, running QA only against the DB view missed:

- 13 rows where `name` was a prefix substring of `address` (name `"2284 Cervera"` vs address `"2284 Cervera, Makati, 1230"`) — the DB `name = address` equality check missed these because the strings weren't equal.
- 90 residual dupes on container categories (LKG Tower, Perla Mansion, Ecoplaza Building) — the DB-side residual-dupe filter had been skipping `container_categories` to avoid transitive drift, but those same clusters showed up in the delivered CSV as obviously the same POI duplicated.

The right pattern is: run the DB-view checks first (fast, catches most), then download the delivered CSV and re-run the checks against it (`from_csv.py`). The LLM decides per cluster, not per pattern — containers should not be auto-skipped.

## Two-layer flow: WIDEN then NARROW

Every check has to go through two passes:

1. **WIDEN (checks.py)** — pattern-based candidate surfacers. Patterns are cheap and catch failure modes we know exist. They are not authorized to approve any action on their own; they only build the candidate pool.

2. **NARROW (verdict.py)** — per-POI LLM reasoning. Each candidate goes through inline judgment with the full context (name, category, address, brand, coords, external IDs, chain membership, provisional status). The LLM decides KEEP vs DELETE, MERGE vs DISTINCT, KEEP vs UNCHAIN. This is where the operator directive lives:

   > "debes ser inteligente, no puede ser por patrones o cosas específicas"

Patterns can never say "this POI is garbage". Only the LLM can. The pattern's role is to say "here's a candidate worth reasoning about".

3. **ACT (act.py)** — takes LLM-labeled inputs (`verdict.delete_ids`, `verdict.merge_pairs`, `verdict.unchain_ids`) and applies the decisions to the DB.

## Actions

| Finding | Verdict path | Action if LLM confirms |
|---------|--------------|------------------------|
| Placeholder name | `verdict_single_placeholder` → DELETE | `act.delete_from_sample_places` |
| name==address | `verdict_single_placeholder` → DELETE | `act.delete_from_sample_places` |
| Short-name | `verdict_single_placeholder` → DELETE/KEEP | `act.delete_from_sample_places` |
| Missed dupe | `verdict_pair_placeholder` → MERGE/DISTINCT | `act.write_merge_pair_csv` → `dupelex.merge_push.trigger_matches_process` |
| chain-cat mismatch | `verdict_single_placeholder` → UNCHAIN/KEEP | `chain.apply.write_observations_csv` (chain_id=null) |

## Why this must run per sample, not just from dupelex

The dupelex report is bounded by score. Pairs that score < 0.5 don't reach us, even if they'd be obvious dupes on inspection (e.g. two `Cebuana Lhuillier Pawnshop - Guadal…` rows with identical coord and identical chain_id, but the name string differs in the last word so name_similarity drops below the report's threshold). This QA layer catches those from the DB side, not the report side.

Similarly, the name-scrub is not something dupelex checks at all — dupelex is a pair-based report, and a single POI with a garbage name doesn't form a pair. The garbage-name scrub is a single-row check that only makes sense at export time.

## Empirical

On sample 9990 (Red Bull PH), after the 1,516-merge dupelex push and sample cleanup, export QA still found:

- 40 placeholder-name POIs (`"Makati"`, `"Manila"`, `"makati city"` as name)
- 47 name==address POIs (compound_building rows with the address string as name)
- 95 same-chain <20m pairs (mostly Eastwest Bank, 7-Eleven, McDonald's, Cebuana Lhuillier — chain-verified same-brand dupes)
- 146 residual name-based dupes at <50m
- 9 chain-cat mismatches (mostly compound/condo names that got a chain_id attached, some legit)
- 314 short names (LLM per-POI needed — many legit brands, some clear noise)

Deleting the 87 clear-garbage (40 + 47) POIs and pushing 200 filtered merges (95 chain-verified + 105 name-based-with-guards) cleaned the sample of anomalies the client would have flagged.
