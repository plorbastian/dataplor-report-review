"""Chain-report filter.

A chain report from DataPlor pairs unchained POIs in a sample against
candidate brand `chain_id`s, with a score and a model-produced
`state ∈ {same, different, unclear}`.

**Actionable rule for UNCHAINED places:** for a place with `chain_id IS
NULL`, the model returns `state="different"` for every candidate
(there is no anchor to say `state="same"` against). So we filter by:

  - place is currently unchained in the DB (chain_id IS NULL), AND
  - candidate rank == 1 (best candidate for this place), AND
  - candidate score >= min_score (default 0.5)

then hand it to the LLM which decides — with brand + POI context —
whether this POI actually belongs to the candidate brand.
"""
import gzip
import json


DEFAULT_MIN_SCORE = 0.5


def load_chain_report(gz_path):
    """Load a chain-report .json.gz emitted by DataPlor's report pipeline.

    Returns the parsed top-level object (usually {"places": [...]}).
    """
    with gzip.open(gz_path, "rt", encoding="utf-8") as f:
        return json.load(f)


def actionable_unchained(report, min_score=DEFAULT_MIN_SCORE):
    """Yield (place_id, candidate) tuples for the rank-1 candidate of each
    unchained place, when the candidate's score >= min_score.
    """
    for entry in report.get("places", []):
        pid = entry.get("place_id")
        candidates = entry.get("candidates") or []
        if not candidates:
            continue
        top = candidates[0]  # rank 1
        try:
            score = float(top.get("score") or 0)
        except (TypeError, ValueError):
            score = 0
        if score < min_score:
            continue
        yield pid, top
