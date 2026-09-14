# Methodology — visits validation (the Javaria pattern)

Post-cleanup check on visitation coverage. Runs after the dupelex + chain + export_qa layers are done and before the export is delivered to the customer.

## The Javaria pattern

A POI in the sample is chained to a `brand` (its `places.chain_id` maps to a `brands.id`). The POI has `estimated_visits_monthly` populated in `places`. But its `places.business_category_id` is NOT in the chained brand's `core_1_category_ids` or `core_2_category_ids`. When the place_export runs, it silently strips visits for that POI.

The client receives the POI in the delivered CSV, with all other columns intact, but every visits field is empty — with no error, no warning, no mention in the delivery note. Analytics downstream will show that POI as "zero visits" and lose signal.

This is the pattern Javaria first surfaced. It is NOT the same as the `business_categories.visitation_enabled=false` strip that runs later in post-export's `nullify_visitation` DQ check — that one is CATEGORY-relative (a park never has meaningful visits regardless of the brand it's chained to). The Javaria strip is BRAND-relative: a `bank` category can be core for one brand and non-core for another.

## Why the strip exists

DataPlor's brand model has three category lists per brand:

- `core_1_category_ids` — the brand's primary business type(s). E.g. Chase Bank → `[bank, atm]`.
- `core_2_category_ids` — adjacent secondary types.
- `business_category_ids` — a broader union used for candidate matching.

Visits are considered reliable only when a POI's own category is in `core_1` or `core_2`. Outside that, the POI might legitimately be a chain-affiliated location (an office building of the bank, a warehouse) whose visits don't reflect customer traffic — so the export strips them.

## The gap

The strip is applied silently, per POI, based on a per-brand configuration operators don't see. A brand whose `core_1_category_ids` was set narrowly (e.g. `[bank]` for BDO) will strip visits from ATM POIs, corporate-office branches, and any related category. On sample 9990 (Red Bull PH), this pattern hit 572 POIs, including 106 BDO branches categorized as `bank`.

The client's use case is what decides whether the strip is a delivery gap. For a beverage brand's retail audit, missing bank-visit data is fine — banks aren't a beverage POS. For an insurance audit that treats bank branches as competitive proxies, the same strip is a delivery gap.

## Flow

1. **Scan** — join `sample_places → places → brands` and bucket every chained POI by (in_core_1 / in_core_2 / in_business_cats_only / outside_all). The "outside_all AND has visits" subset is the Javaria set.
2. **Verdict** — LLM inline per POI, given the POI context, the brand's category config, and the customer's use-case description. Labels: `ACCEPT_STRIP` / `DELIVERY_GAP` / `UNCLEAR`.
3. **Act** — for `DELIVERY_GAP` verdicts, either drop the POI from the sample (client won't see zero-visit ghosts) or attach a delivery note listing the affected POIs (client sees them, understands why visits are missing).

## Not a rules engine

Do not decide by category alone. `bank` is not universally core; `corporate_office` is not universally non-core. The right verdict comes from reading the POI's specific context alongside the brand's config alongside the customer's intent.

## Empirical on sample 9990 (Red Bull PH, 2026-09-14)

- 572 chained POIs sit in the outside_all bucket AND have visits.
- 106 are BDO (Banco de Oro) branches categorized as `bank` — but BDO's `core_1_category_ids` apparently does not include `bank` on this brand config.
- 23 Metrobank, 20 Unionbank, 17 Watsons, 14 BPI — same pattern.

For a Red Bull retail audit these are almost certainly `ACCEPT_STRIP` — banks aren't relevant to beverage POS. But for the next customer whose use case DOES value bank-branch traffic, the same 572 POIs are a delivery gap that this check catches before the CSV ships.
