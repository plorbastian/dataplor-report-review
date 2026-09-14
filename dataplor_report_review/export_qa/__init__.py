"""export_qa — post-cleanup DQ checks against sample_places JOIN places.

Run this after dupelex + chain have landed and Phase 5 cleanup has run.
The checks reproduce the joins the client-facing `place_export` will
perform, and surface anomalies that a downstream client-side DQ pass
tends to flag — the kind of issues that make a delivered CSV look
unpolished even when the underlying rows are technically valid.

Layered by design:

  checks.py  — WIDEN the candidate pool with cheap indicators (name
               length, name-address equality, chain-cat mismatch,
               same-name/same-chain proximity).
  verdict.py — NARROW to real issues via inline LLM reasoning per POI
               (or per pair). Patterns never approve on their own; the
               LLM is the decider.
  act.py     — APPLY the LLM verdicts: DELETE from sample_places for
               garbage, matches:process merges for missed dupes.

Every check function returns raw candidates. Every action function
takes LLM-labeled inputs. Callers must wire an LLM verdict function
between the two — see `verdict.py` for the reference signatures.
"""
from . import checks, verdict, act, components, from_csv

__all__ = ["checks", "verdict", "act", "components", "from_csv"]
