# dupelex-llm-review

Standardized 7-phase methodology for reviewing DataPlor `dupelex` reports at scale, POI-por-POI, with LLM inline reasoning and multi-layer safety filters against transitive-drift false positives.

## Why this exists

A raw dupelex report over a large sample (e.g. `sample_id=9990`, ~59K places, Metro Manila) produces on the order of **30 million candidate pairs**. Only a tiny fraction are actual dupes. Naive score-thresholding + auto-merge collapses distinct POIs together (a mall + its tenants, a hospital + its departments, an office building + its subsidiaries) — the classic "Chase-ATM pattern" and "container+tenant" failure modes.

This package encodes the reviewer methodology we developed to make dupelex safe at scale:

1. **Filter** the raw 30M pairs down to an actionable set using a strong-signals rule.
2. **Enrich** each pair from `places_read_metal` with full context + external IDs.
3. **Chase-ATM guard** — reject when two POIs are distinguishable (different `gpid`, different URL slug, different Yext source).
4. **Category-family guard** — reject when categories cross incompatible families (bank vs restaurant).
5. **Refined re-guard** — override the guard when the same-name/close-coords/shared-host pattern actually indicates a Google double-index.
6. **LLM POI-por-POI** — for ambiguous middle-tier pairs, apply inline reasoning per pair (not pattern rules) with full context.
7. **Component safety** — union-find over the merge graph, then reject any pair that connects into a large component (size ≥ 5) with non-identical names (kills transitive drift).

The output is a clean pair CSV ready for `matches:process` on Fargate, plus a downstream **sample_places** cleanup + verification step.

## The 7 phases

| Phase | Module | Input | Output |
|-------|--------|-------|--------|
| 1. Filter | `filter.py` | raw dupelex CSV.gz (~30M rows) | actionable pairs CSV (~20K rows) |
| 2. Enrich | `enrich.py` | actionable pairs + DB | pairs with full context, external_ids |
| 2b. Guard | `guard.py` | enriched pairs | tiered: auto_accept / high_conf / medium / reject_guard / reject_category |
| 2c. Reguard | `reguard.py` | reject_guard bucket | overrides for same-name + supporting-signal cases |
| 3. LLM Review | `llm_review.py` | medium tier | verdicts MERGE / DISTINCT / UNCLEAR per pair |
| 3.5. Safety | `safety.py` + `strict.py` | consolidated merge pair list | strict-name components, container+tenant rejects, practitioner rejects |
| 4. Push | `merge_push.py` | final pair CSV | matches:process rake task on Fargate |
| 5. Cleanup | `sample_cleanup.py` | sample_id | DELETE from sample_places WHERE parent_id IS NOT NULL |
| 6. Verify | `verify.py` | sample_id | prod + places_read_metal state check |

## Failure modes this catches

- **Chase-ATM pattern** — two POIs at the same coordinates with matching name+phone but different `google_places_id` → distinct.
- **Container+tenant** — a shopping mall row and a tenant row both named "Foo Mall" → distinct.
- **Practitioner sharing a building** — 15 doctors at the same medical center address, all `Dr. X @ Makati Med` → distinct.
- **Subsidiaries** — "BPI ATM" + "BPI Leasing" + "BPI Forex" + "BPI Foundation" all at HQ address → distinct.
- **Rebrand/naming variants** — the same POI indexed as "Popeyes Chicken - Kroma" and "Popeyes Louisiana Kitchen" at the same address → merge.
- **Transitive drift** — pair A↔B (legit) + B↔C (legit) + C↔D (legit) forms a size-4 component; strict-name filter enforces "all four normalize to the same name" before allowing the merge.

## Origin

Developed while processing the DataPlor Red Bull PH sample_id=9990 dupelex report (id=514683), 2026-09-14. See [docs/methodology.md](docs/methodology.md) for the full reasoning trace behind each rule and the specific failure cases that motivated each safety filter.

## Not a rules engine

The LLM review step deliberately uses inline reasoning per pair, not hardcoded regex rules. Patterns are used only as **rejection safeties** (never as approval shortcuts) — the operator's directive was:

> "debes ser inteligente, no puede ser por patrones o cosas específicas"

Approval decisions require per-POI context (address, category, brand, coordinates, external IDs) evaluated together, not matched against a shortlist.
