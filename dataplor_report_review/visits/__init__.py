"""visits — validation of visitation coverage on chained POIs.

The Javaria pattern (named after the SE who first surfaced it): a POI is
chained to a `brand`, has visits populated in the DB, but its
`business_category_id` is NOT in the brand's `core_1_category_ids` and
NOT in its `core_2_category_ids`. When the place_export runs, it strips
the visits for that POI silently, and the client receives the POI with
zero visits data even though the underlying DB row had them.

This is different from the `business_categories.visitation_enabled=false`
strip (which happens later, in post-export's `nullify_visitation` DQ
check). The core_1/core_2 strip is BRAND-relative: the same category
may be core for one brand and non-core for another.

Concretely on sample 9990 (Red Bull PH), 572 chained POIs fall in this
bucket — including 106 BDO branches, 23 Metrobank, 20 Unionbank —
categorized as `bank` but not in the brand's core lists. Silent visit
loss.

Modules:
  scan    — bucket chained sample POIs by core_1 / core_2 / outside;
            surface the "outside with visits" cohort (the Javaria set).
  verdict — LLM POI-per-POI: given the customer's use case, is this
            visit strip a delivery gap or acceptable?
  act     — drop from sample OR emit a delivery note attachment.
"""
from . import scan, verdict, act

__all__ = ["scan", "verdict", "act"]
