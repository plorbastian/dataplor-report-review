# Methodology — dupelex LLM review

This document explains WHY each phase is shaped the way it is, based on the specific failure modes we hit reviewing DataPlor dupelex reports in production.

## Context

A `dupelex` report is DataPlor's exhaustive pair-candidate output for a sample: every combination of places within a proximity threshold, scored by name/address/phone/website/coordinate similarity. On a large sample (e.g. `sample_id=9990`, ~59K places in Metro Manila), the raw report is ~30 million pairs and ~6 GB. Only a tiny fraction (~0.005%) are actual duplicates.

Naive filtering (`score >= 0.8` → auto-merge) generates catastrophic false positives:

- A mall row merges with each of its ~50 tenant rows because Google indexes tenants with the mall name in their record.
- A hospital row merges with 100+ doctor and department rows because they all share the hospital's coordinates.
- Two banks (e.g. PSBank and PS Bank) with different Google Places IDs get merged because their name/website/phone/coords all match.

The methodology below is designed to catch each of these failure modes explicitly.

## Phase 1 — filter raw

**Rule:** keep only pairs where `score >= 0.5` AND at least one strong signal is present:

- `name_similarity >= 0.9`, OR
- coordinates within 50m, OR
- `exact_phone`, OR
- `exact_website`, OR
- shared `location_parent_id`.

**Why:** low-score pairs (e.g. `score=0.2` on distant same-name matches) are noise. Score alone isn't enough — a `score=0.85` pair with `name_sim=0.4`, `coords=200m`, no phone, no website is not actionable. Requiring at least one strong signal drops most low-quality candidates and reduces the DB context load by ~1500x.

**Empirical:** 29,497,935 raw pairs → 20,858 actionable pairs on sample 9990 (~14 min stream through the .csv.gz).

## Phase 2a — DB enrichment

Pulls both places' full context (address, category, chain, website, phone, coordinates, provisional flag, external IDs) into a per-pair dict. The pair CSV alone doesn't carry enough context for judgment — you need `business_category_id`, `parent_id`, and especially `external_ids.google_places_id`.

## Phase 2b — the Chase-ATM guard + category-family guard

**The Chase-ATM pattern** was named after a specific 2026 failure: two Chase ATMs at the same intersection, both with score ≥ 0.95, name similarity ≥ 0.9, exact phone, exact website, coordinates within 5m — but different `google_places_id`. They are distinct machines, not duplicates.

**Rule:** a pair FAILS the guard when any of the following diverge:
- `google_places_id` (both present and different).
- URL slug (both non-empty, both > 3 chars, neither is a prefix of the other).
- `yext_source` (both present and different).

**The category-family guard** rejects pairs whose categories are in incompatible families (bank vs restaurant, hotel vs medical, school vs retail). Not every category is in a family — most retail categories are open — but cross-family matches are almost always FPs.

**Tiering after both guards:**

| Bucket | Rule | Meaning |
|--------|------|---------|
| `auto_accept` | `name_sim >= 0.99` + at least one strong signal + passes guards | Trusted merge |
| `high_conf` | `name_sim >= 0.9` + strong signal + passes guards | Trusted merge |
| `medium` | Passes guards but ambiguous | Hand off to Phase 3 |
| `reject_guard` | Fails Chase-ATM guard | Distinct POIs |
| `reject_category` | Cross-family category | Distinct POIs |

## Phase 2c — refined re-guard

The Chase-ATM guard is aggressive. It also catches legitimate dupes where Google indexed the same POI under two `gpid`s (a common outcome after a listing merge or when a store appears both at a mall-level and street-level).

**Override rules on the `reject_guard` bucket:**

1. If names are exactly equal (`name_sim >= 0.99`) AND any supporting signal → promote to `auto_accept`.
2. If `name_sim >= 0.9` AND any supporting signal → promote to `high_conf`.
3. If same website host AND coordinates < 20m → promote to `high_conf`.
4. If `name_sim >= 0.7` AND at least 2 strong signals → promote to `medium` (defer).

**Why:** the same-name-plus-same-store-signal pattern is much stronger evidence than the gpid difference is. But we still hold `medium` back for the LLM in ambiguous ranges.

**Failure case that motivated this:** PSBank vs PS Bank (name similarity ≈ 0.95, same website, coordinates 3m apart, but different gpids). The naive guard rejected them as distinct. The refined rule 2 lets them merge.

## Phase 3 — LLM POI-por-POI

For pairs still in `medium` after Phase 2c, no rule can decide. Each pair needs inline reasoning across the full context:

- Are the address strings the same specific unit, or the same building with different unit numbers?
- Are the categories the same intent (both "coffee_shop") or distinct roles at a shared location (a coffee shop vs a lobby coffee stand)?
- Does the brand prefix in the name match a chain, and is that brand plausibly duplicated at this coord?
- Do the coordinates map to the same specific storefront, or the same block?

**The operator directive:**

> "debes ser inteligente, no puede ser por patrones o cosas específicas"

The LLM step must NOT be a hardcoded rules engine. Patterns can be used for **rejection safeties** (Phase 3.5), but merge approval must come from per-POI reasoning.

**Bulk pre-pass:** before the LLM, we do promote a subset of `medium` on pure string equality. `name_similarity` from the dupelex pipeline can misfire on identical strings due to tokenization quirks (e.g. "Inengs special bbq" scoring 0.33 against itself). If the normalized name strings are literally equal AND the categories match, we trust the equality.

## Phase 3.5a — safety filter

Four *rejection-only* patterns applied to the consolidated merge list. Each pattern captures a specific failure mode we observed producing false positives:

1. **Container + tenant** — one place is a `shopping_center`/`medical_center`/`corporate_office`/etc., the other is not, and their names differ. The mall row and the Zara row inside the mall are not duplicates.

2. **Practitioners with different names** — both places share an address (a medical center, a law firm) but the names identify different practitioners. Fifteen doctors sharing an address are fifteen POIs.

3. **Distinct brand prefixes** — when `name_similarity < 0.5`, if the first-word of each name is a different non-generic brand (Zara vs Sbarro), reject. Common at malls where transitive links via a shared parent chain distinct brands into one component.

4. **Hospital departments** — both names contain the hospital name AND at least one contains a department keyword (Office of the / Section / Department), and names disagree → distinct departments.

**These are NEVER approval patterns** — they only reject. Not being rejected by any of these does not mean the pair should merge. Only the guards + LLM judgment authorize a merge.

## Phase 3.5b — strict-name over big components

Union-find over the surviving merge pair graph. If a pair sits in a component of size ≥ 3, we require both places' normalized names (lowercased, punctuation stripped, whitespace collapsed) to be equal. Otherwise we drop the pair.

**Why this is required:** consider three legit pairs (A↔B, B↔C, C↔D). Each pair evaluated in isolation passes every guard. But the union-find groups them into a 4-way component. If A, B, C, D are truly the same POI, they'll all normalize to the same string. If any of them differs, one of the "legit" pairs was actually crossing between two distinct real-world POIs.

**Empirical:** on sample 9990, this filter caught 52 additional drift pairs after all earlier safety checks. Without it, three size-15 components would have merged: 15 Makati Medical Center departments + doctors + one ATM (into one POI), 15 Power Plant Mall stores + the mall itself (into one POI), 15 distinct doctors at the same address (into one POI).

**An allowlist** is supported: hand-approved LLM verdicts where names legitimately differ (e.g. "Popeyes Chicken - Kroma" ↔ "Popeyes Louisiana Kitchen" for the same restaurant) bypass the strict-name rule.

## Phase 4 — matches:process

Write the final merge pair CSV in `id_a,id_b,score` format and invoke DataPlor's `bulk_observations/match_processor/process_matches.py`. That script:

1. Uploads the payload to `s3://dataplor-data/presales/match_processor/`.
2. POSTs `/v3/admin/rake_tasks` to fire the `matches:process` rake on the heavy-worker Fargate cluster.
3. Polls the container task until `platform_task_completed_at`.

MatchProcessorService in DataPlor picks the parent by data richness — the survivor of each merge is not necessarily the one you passed as `id_a`.

## Phase 5 — sample_places cleanup

Once merges land, every child (`places.parent_id IS NOT NULL`) that was in `sample_places` for the affected sample must be deleted. Otherwise the next `place_export` job delivers a CSV that includes both parent and child, showing the client duplicates they already saw.

Use the `prod` role (`places_read_metal` is read-only). Delete by explicit place_id list rather than a JOIN — a full-sample DELETE with a JOIN can exceed the statement timeout on large samples.

## Phase 6 — verification

Compare the same counts against both the `prod` cluster and the `places_read_metal` read replica. The replica lags by ~5 minutes; polling every 30 seconds until parity is a good pattern.

Three counts to check:

1. `sample_places` count matches between roles.
2. Zero rows in `sample_places` for the sample whose place has a non-null `parent_id`.
3. Of the child place_ids from the merge list, ≥ 95% have `parent_id` set in both roles.

Any discrepancy at t+5min means either a slow replica or a subset of merges silently failed — investigate the container task logs.
