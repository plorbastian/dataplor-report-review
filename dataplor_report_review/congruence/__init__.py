"""congruence — three-way parity between DB, place_export, post-export.

Every sample flows through three surfaces before it reaches the customer:

  1. DB     — sample_places JOIN places (places_read_metal).
  2. export — the place_export CSV in S3 (customer-facing columns +
              dataplor_id UUID as the row key).
  3. post_export — the sample_forge post-export pipeline outputs
                    (DQ-cleaned, geographically clipped to the boundary,
                    trimmed, rewritten, assembled). What the customer
                    actually receives.

They MUST agree on the same POIs, at the same counts, with the same
chain/visitation coverage, or something silently dropped between stages.

Modules:
  db_vs_export         — sample_places row count + chain coverage vs the
                         delivered CSV.
  export_vs_postexport — CSV row count + column coverage vs the
                         post-export final artifact.
  three_way_report     — consolidated diff table + LLM narrative of what
                         changed at each stage.
"""
from . import db_vs_export, export_vs_postexport, three_way_report

__all__ = ["db_vs_export", "export_vs_postexport", "three_way_report"]
