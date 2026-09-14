"""export_qa — post-cleanup QA checks against sample_places JOIN places.

Run this after dupelex + chain have landed and Phase 5 cleanup has run.
The checks reproduce the joins the client-facing `place_export` will
perform, and surface anomalies that Alison-style QA (IDCTECH incident,
2026-09-08) tends to flag:

  short_names            names of <=3 chars (some legit brands, most noise)
  placeholder_names      city / country placeholders as the POI name
  numeric_only_names     names that are only digits/symbols
  name_equals_address    name is literally the address string
  chain_cat_mismatch     chain_id set on incompatible category
  residual_name_dupes    same normalized name + <50m + missed by dupelex
  same_chain_close       same chain_id + <20m + missed by dupelex
"""
from . import checks, act

__all__ = ["checks", "act"]
