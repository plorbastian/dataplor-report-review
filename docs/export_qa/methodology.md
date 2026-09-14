# Methodology — post-cleanup export QA

Third pillar of the review methodology. Runs AFTER dupelex + chain have landed and after Phase 5 sample_places cleanup. This is the "Alison layer" — named for the IDCTECH incident (2026-09-08) where a client-side QA pass surfaced two categories of errors that the dupelex pipeline had not caught:

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

## Actions

| Finding | Action | Path |
|---------|--------|------|
| Placeholder name | DELETE from `sample_places` (keep row in `places`) | `act.delete_from_sample_places` |
| name==address | DELETE from `sample_places` | `act.delete_from_sample_places` |
| Short-name garbage (LLM-confirmed) | DELETE from `sample_places` | `act.delete_from_sample_places` |
| Missed dupe (LLM-confirmed) | MERGE via `matches:process` | `act.write_merge_pair_csv` → `dupelex.merge_push.trigger_matches_process` |
| chain-cat mismatch (LLM-confirmed FP) | Write `/chain_id` NULL observation | `chain.apply.write_observations_csv` (value=null) |

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
