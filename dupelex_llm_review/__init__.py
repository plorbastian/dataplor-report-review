"""dupelex-llm-review: 7-phase methodology for DataPlor dupelex review at scale.

Modules:
  filter       — Phase 1: raw dupelex → actionable pairs
  enrich       — Phase 2a: DB context + external IDs
  guard        — Phase 2b: Chase-ATM + category-family guards → tiered buckets
  reguard      — Phase 2c: refined guard for override cases
  llm_review   — Phase 3: LLM POI-por-POI verdicts on medium tier
  safety       — Phase 3.5a: container+tenant, practitioner, brand-prefix rejects
  strict       — Phase 3.5b: big-component strict-name filter
  merge_push   — Phase 4: matches:process rake task on Fargate
  sample_cleanup — Phase 5: DELETE merged children from sample_places
  verify       — Phase 6: prod + places_read state check
"""
__version__ = "0.1.0"
