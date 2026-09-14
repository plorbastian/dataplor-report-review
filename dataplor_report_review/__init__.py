"""dataplor-report-review: standardized LLM-assisted review of DataPlor
sample reports (chain + dupelex) with production-side propagation.

Two workflows, one repo:

  dupelex/  — pairwise duplicate review with multi-layer safety filters
              against transitive drift (container+tenant, practitioner,
              big-component strict-name).

  chain/    — per-POI chain-membership review for unchained candidates
              in a sample, driven by brand context and category
              constraints, applied via /chain_id observations.

Both flows share:
  - Sebastian's admin_id (42476) for observations attribution.
  - `places_read_metal` for enrichment (read replica).
  - `prod` for writes (DELETE from sample_places, observations table).
  - The DataPlor api.dataplor.com pattern for rake tasks on Fargate.
"""
__version__ = "0.2.0"
