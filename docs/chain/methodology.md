# Methodology — chain report LLM review

Companion to the dupelex methodology. Covers the workflow for reviewing DataPlor `chain` reports at scale — assigning `chain_id` to previously unchained POIs in a sample.

## What a chain report is

For a given sample, DataPlor's chain analyzer pairs each unchained POI against a shortlist of candidate `chain_id`s (brand slugs) ordered by score, and emits a model-produced `state ∈ {same, different, unclear}` per candidate. The report ships as a compressed JSON blob on S3.

## The unchained-state trap

The natural filter — "keep only candidates where `state=same`" — is **wrong** for unchained POIs. When a place has `chain_id IS NULL` there is no anchor for the model to say `state=same` against; it returns `state=different` for every candidate even when the top candidate is obviously the right brand. The correct filter for the unchained pool is:

```
place.chain_id IS NULL
AND candidate.rank == 1
AND candidate.score >= 0.5
```

Then let the LLM decide per-POI whether the top-rank candidate is the actual brand of this POI. This is the source of the ~90% of legitimate chain additions that a naive `state=same` filter misses on unchained places.

## Per-POI reasoning (not category matching)

Chain analyzer produces a candidate list from name similarity. The LLM's job is to verify the pairing with the full context:

- **Name match** — is the POI's name the brand name, an alias, or a namesake?
- **Category compatibility** — is the POI's `business_category_id` in the brand's `allowed_categories` and NOT in `banned_categories`? Category alone is not sufficient (a "Mercury Drug" pharmacy chain sharing name with a person named Mercury). Category is a gate, not a decider.
- **Website root** — does the POI's website match the brand's `website_root` (or a subdomain / country locale of it)?
- **Country** — does the POI's country match the brand's `country_code`?
- **Namesake detection** — brand names that overlap with common surnames (Cebuana, Carmen) or city names (Makati) generate false positives that the LLM must catch by looking at the POI's category and website.

Verdicts:

- **APPLY** — POI belongs to this brand; write `/chain_id` observation.
- **SKIP** — POI does not belong; leave unchained.
- **UNCLEAR** — cannot decide; leave unchained. Safe default; the operator can re-review later.

## Application via mass_observations.py

The canonical path for `/chain_id` writes is presales_tools' `bulk_observations/mass_observations.py`. It:

1. Uploads a CSV of observations to S3 (`s3://dataplor-data/presales/manual_observations/`).
2. Fires the `observations:apply` rake task on Fargate via `POST /v3/admin/rake_tasks`.
3. Enqueues Sidekiq `place_tree_updater` jobs on the `place_tree_updater` queue so `places.chain_id` propagates through the tree.

Sebastian's `admin_id=42476` is the correct attribution — never Ross's `440711`.

## Verification

After the observations apply and the PTU jobs drain, verify in both roles:

- `places_read_metal` chain_id for each APPLY place matches the expected slug (accounting for ~5min replica lag).
- Sample-level total chained count matches between prod and places_read.

For sample 9990 in this repo's genesis run, 292 chain_id observations landed (266 Fase A chain report + 26 Fase B brandisco), verified with parity in both roles.

## Related failure modes

- **Global chain reports apply spurious geo penalty** — for country-scoped audits, always run the report with country_code scoping. Global reports penalize POIs whose city doesn't match the brand's dominant city.
- **rfi=false silently guts chain reports** — a brand with `ready_for_identification=false` at report time returns near-empty candidate lists. Verify `brands.ready_for_identification=true` before running.
- **Chain trigger MUST use `arguments.country_code`** — using geos OSM IDs instead corrupts the country scoping.
