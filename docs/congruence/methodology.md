# Methodology — DB ↔ export ↔ post-export congruence

Every sample flows through three surfaces before it reaches the customer:

1. **DB** — `sample_places JOIN places` on `places_read_metal`. This is the authoritative view of what belongs to the sample.
2. **place_export CSV** — the file DataPlor's exports pipeline drops in S3, keyed by `dataplor_id` UUID. This is what post-export consumes.
3. **post-export final artifact** — `{sid}_final.csv` produced by sample-forge's `run-pipeline`. This is what the customer actually receives.

Between each pair we expect a specific, defensible delta:

| Transition | Expected changes | Never OK |
|------------|------------------|----------|
| DB → export | none: every sample_places row should appear in the CSV with the correct UUID | rows missing from CSV; merged children leaking in; chain_id count mismatch |
| export → post-export | POIs outside boundary dropped; some visits nullified; columns rewritten | rows added that weren't in export; mass strip of a customer-required column |

The three-way check consolidates both deltas and surfaces any that look wrong.

## Cross-references

- The visits strip surfaced here is BOTH the Javaria strip (chain-relative, happens in export) and the post-export `nullify_visitation` strip (category-relative). Interpreting a large strip against the customer's use case is the job of `visits/verdict.py`, not this module.
- The boundary drop is what sample-forge's `clip` stage does — expected. The count should roughly match the "outside" count from the pipeline log's `Containment results: total=X inside=Y outside=Z` line.

## Invariants

Zero-tolerance findings that must be resolved before delivery:

1. `db_vs_export.in_sp_not_in_csv > 0` — the sample references a POI the export did not emit. Something is broken between sample_places and the export pipeline. Investigate before delivery.
2. `db_vs_export.leaked_children_in_csv > 0` — a merged child (place with `parent_id IS NOT NULL`) is in the export. This means either (a) the sample_places cleanup step (Phase 5 of the dupelex flow) was skipped, or (b) the export was generated before the cleanup landed.
3. `export_vs_postexport.added_by_pipeline > 0` — the pipeline emitted rows that weren't in the raw export. This can only happen if something is wrong with the join keys or a rewrite is unioning in additional data. Investigate.

## Advisory findings

Non-blocking, but worth capturing in the delivery note:

- Boundary drops (`pipeline: total=X inside=Y outside=Z`) — the customer's ticket may have implied a wider geography than the boundary R-code covers.
- Visit strips on core categories — cross-reference the visits module for the LLM verdict per POI.
