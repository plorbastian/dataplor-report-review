"""chain sub-package — LLM-assisted chain report review.

Phases:
  fetch         — download the chain report .json.gz from DataPlor S3
  filter        — extract actionable candidates (chain_id IS NULL, score >= 0.5)
  enrich        — pull brand context + POI context from the DB
  llm_review    — POI-por-POI verdict per candidate ("does this POI belong to this brand?")
  apply         — write /chain_id observations via mass_observations.py
  trigger_ptu   — enqueue place_tree_updater jobs so places propagate
  verify        — confirm chain_id set in prod + places_read

See docs/chain/methodology.md for the reasoning behind each rule.
"""
from . import filter, enrich, llm_review, apply, verify

__all__ = ["filter", "enrich", "llm_review", "apply", "verify"]
