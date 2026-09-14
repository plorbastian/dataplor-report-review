"""remediate — decide + apply fixes for canonical-check findings.

Pipeline:

  canonical_check.json (from sample-forge)
    → for each finding, LLM inline decides:
        FIXABLE_NOW      — per-POI observation write clears it
        SYSTEMIC         — mass ingest / scraper bug; escalate to DQ
        DELIVERY_NOTE    — flag in the delivery, don't fix upstream
        IGNORE           — false positive
    → apply FIXABLE_NOW via observations + PTU
    → LLM decides again: does the fix require a NEW place_export?
        YES  — trigger export_job + wait + re-run post-export
        NO   — the current CSV is still authoritative for delivery

Modules:
  triage    — read canonical_check.json, LLM verdict per finding
  fix       — write observations, trigger PTU
  reexport  — decide re-export + trigger export_job on api.dataplor.com
"""
from . import triage, fix, reexport

__all__ = ["triage", "fix", "reexport"]
