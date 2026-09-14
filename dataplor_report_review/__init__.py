"""dataplor-report-review: standardized LLM-assisted review of DataPlor
sample reports (chain + dupelex + export QA) with production propagation.

Three workflows, one repo:

  dupelex/    — pairwise duplicate review with multi-layer safety filters
                against transitive drift (container+tenant, practitioner,
                big-component strict-name).

  chain/      — per-POI chain-membership review for unchained candidates
                in a sample, driven by brand context and category
                constraints, applied via /chain_id observations.

  export_qa/  — post-cleanup DQ checks on the sample_places JOIN places
                view the client-facing place_export reads from. Catches
                garbage names (placeholders, name==address, unit labels)
                and residual dupes the dupelex report missed at the
                pair-report threshold.

Shared plumbing:
  - Sebastian's admin_id (42476) for observations attribution.
  - `places_read_metal` for enrichment (read replica).
  - `prod` for writes (DELETE from sample_places, observations table).
  - The DataPlor api.dataplor.com pattern for rake tasks on Fargate.
"""
__version__ = "0.3.0"
