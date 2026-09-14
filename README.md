# dataplor-report-review

Standardized LLM-assisted methodology for reviewing DataPlor sample reports at scale, POI-por-POI, with production propagation and safety filters against systematic false positives.

Six workflows in one repo:

- **`dupelex/`** — pairwise duplicate review (Chase-ATM guard, category-family guard, refined re-guard, LLM medium tier, container+tenant safety, big-component strict-name filter).
- **`chain/`** — per-POI chain-membership review for unchained candidates in a sample (unchained-state trap, brand-context enrichment, category compatibility, per-POI LLM verdicts).
- **`export_qa/`** — post-cleanup DQ checks on the `sample_places JOIN places` view the client-facing `place_export` reads from. Catches garbage names (city placeholders, unit labels, name==address rows) and residual dupes below the dupelex report threshold.
- **`visits/`** — the Javaria pattern: chained POIs whose `business_category_id` is not in the brand's `core_1_category_ids` / `core_2_category_ids` get their visits silently stripped at export time. LLM per-POI verdict against the customer's use case.
- **`congruence/`** — three-way DB ↔ export ↔ post-export parity. Row-count, UUID coverage, chain coverage, no phantom rows, no leaked children, defensible column strips.
- **`darc_check/`** — DARC form (Google Sheet) vs Linear ticket vs `samples.schema` vs sample-forge's `canonical_check.json` — reconcile the four surfaces so nothing silently drifts.

Both flows share the DataPlor plumbing:

- `places_read_metal` for enrichment (read replica, ~5min lag).
- `prod` cluster for writes (DELETE from `sample_places`, observations, chain_id).
- `api.dataplor.com/v3/admin/rake_tasks` on Fargate for `matches:process` and `observations:apply`.
- Sebastian's `admin_id=42476` for attribution.

## Why this exists

Naive score-thresholding on either report type produces catastrophic false positives at scale:

- **Dupelex** — a mall row merges with each of its ~50 tenant rows because Google indexes tenants with the mall name in their record. A hospital row merges with 100+ doctor and department rows. Two banks (e.g. PSBank and PS Bank) with different Google Places IDs get merged because their name/website/phone/coords all match.
- **Chain** — a naive `state="same"` filter misses ~90% of legitimate chain additions on unchained POIs, because the model returns `state="different"` for every candidate when there's no anchor.

The methodology below is designed to catch each failure mode explicitly, with per-POI LLM reasoning as the decider (never regex or hardcoded rules on the approval path).

## dupelex — 7 phases

| Phase | Module | Input | Output |
|-------|--------|-------|--------|
| 1. Filter | `dupelex.filter` | raw dupelex .csv.gz (~30M rows) | actionable pairs CSV (~20K rows) |
| 2. Enrich | `dupelex.enrich` | actionable pairs + DB | pairs with full context, external_ids |
| 2b. Guard | `dupelex.guard` | enriched pairs | tiered: auto_accept / high_conf / medium / reject_guard / reject_category |
| 2c. Reguard | `dupelex.reguard` | reject_guard bucket | overrides for same-name + supporting-signal cases |
| 3. LLM Review | `dupelex.llm_review` | medium tier | verdicts MERGE / DISTINCT / UNCLEAR per pair |
| 3.5. Safety | `dupelex.safety` + `dupelex.strict` | consolidated merge list | strict-name components, container+tenant + practitioner rejects |
| 4. Push | `dupelex.merge_push` | final pair CSV | matches:process rake task on Fargate |
| 5. Cleanup | `dupelex.sample_cleanup` | sample_id | DELETE from sample_places WHERE parent_id IS NOT NULL |
| 6. Verify | `dupelex.verify` | sample_id | prod + places_read state check |

**Failure modes this catches:** Chase-ATM pattern, container+tenant (mall + Zara), practitioner sharing a building (15 doctors + Makati Med + BDO ATM), subsidiaries (BPI Leasing + BPI Foundation), rebrand naming variants (Popeyes Chicken vs Popeyes Louisiana Kitchen), transitive drift (A↔B + B↔C + C↔D forming a 4-way false component).

Full write-up: [docs/dupelex/methodology.md](docs/dupelex/methodology.md).

## chain — 6 phases

| Phase | Module | Input | Output |
|-------|--------|-------|--------|
| 1. Filter | `chain.filter` | chain report .json.gz | rank-1 candidates for unchained POIs, score >= 0.5 |
| 2. Enrich | `chain.enrich` | candidates + DB | place context + brand context (allowed/banned cats, aliases, website root) |
| 3. LLM Review | `chain.llm_review` | candidates + context | verdicts APPLY / SKIP / UNCLEAR per POI |
| 4. Apply | `chain.apply` | APPLY verdicts | write /chain_id observations via mass_observations.py |
| 5. PTU | (via `mass_observations.py`) | S3 obs payload | enqueue place_tree_updater jobs on Fargate |
| 6. Verify | `chain.verify` | sample_id | prod + places_read chain coverage parity |

**Failure modes this catches:** unchained-state trap (state=different for every candidate), namesake false positives (brand names that overlap with surnames or city names), country-scope drift (global chain reports vs country-scoped reports), rfi=false suppression (silent empty candidate lists when the brand's `ready_for_identification=false`).

Full write-up: [docs/chain/methodology.md](docs/chain/methodology.md).

## export_qa — post-cleanup anomaly checks

Runs AFTER dupelex + chain have landed. Reproduces the client-facing `sample_places JOIN places (places_read_metal)` view and surfaces anomalies.

| Check | What it catches | Action |
|-------|-----------------|--------|
| `short_names` | Names ≤3 chars, digits-only, symbols-only | LLM per-POI (many legit brands like K2, LG) |
| `placeholder_names` | Names like `"Makati"`, `"Manila"`, `"Suite"` | DELETE from sample_places |
| `name_equals_address` | `name = address` exactly | DELETE from sample_places |
| `chain_cat_mismatch` | chain_id set on hospital / condo / church / apartment | LLM per-POI (some legit) |
| `residual_name_dupes` | Same normalized name + <50m, missed by dupelex | MERGE via matches:process |
| `same_chain_close` | Same chain_id + <20m, missed by dupelex | MERGE via matches:process |

Full write-up: [docs/export_qa/methodology.md](docs/export_qa/methodology.md).

## Origin

Developed while processing DataPlor sample_id=9990 (Red Bull PH, Metro Manila) on 2026-09-14:

- **Chain report:** 292 chain_id observations landed (266 Fase A chain report + 26 Fase B brandisco), verified in both roles.
- **Dupelex report 514683:** 29,497,935 raw pairs → 1,516 confirmed merges pushed via `matches:process` (container task 295411). Sample dropped 59,314 → 57,891 POIs. Zero dirty children in either role. Four size-15 false-positive clusters (Makati Medical Center + doctors, Power Plant Mall + tenants, SyCipLaw firm + 10 lawyers) blocked by the safety filters — those would have collapsed dozens of distinct POIs into one.
- **Export DQ pass:** post-cleanup checks against sample 9990 found and cleaned 87 garbage-name POIs (40 city-placeholder names, 47 name==address) + pushed 200 more chain-verified missed dupes via `matches:process` (95 same-chain <20m + 105 name-based <20m). These would have shown up as anomalies in the client-facing export.

## Not a rules engine

The LLM review steps deliberately use inline reasoning per POI, not hardcoded regex rules. Patterns appear only as **rejection safeties** (never as approval shortcuts):

> "debes ser inteligente, no puede ser por patrones o cosas específicas"

Approval decisions require per-POI context (name, address, category, brand, coordinates, external IDs, chain membership) evaluated together, not matched against a shortlist.
