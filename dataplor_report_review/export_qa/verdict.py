"""LLM-verdict layer for export_qa candidates.

The checks in `checks.py` are candidate surfacers — they widen the net
based on cheap indicators (name length, name-address equality, chain-cat
mismatch). Every candidate must go through per-POI LLM reasoning here
before we act on it. Patterns are ONLY used to WIDEN the candidate pool
(rejection safeties never approve on their own); the actual APPROVE
decision is always LLM-inline.

The operator directive that drives this module:

  "debes ser inteligente, no puede ser por patrones o cosas específicas"

Verdicts (per candidate type):

  short_name / placeholder_name / name==address:
      DELETE  — the POI has no real business identity in this record
      KEEP    — legit business whose real name happens to be short
                (K2, LG, RT) or whose registered name literally is the
                street address
      UNCLEAR — cannot decide

  chain_cat_mismatch:
      UNCHAIN — chain_id was attached in error; write /chain_id=null obs
      KEEP    — legit case (bank branch inside a condo, worship
                organization officially named after a district)
      UNCLEAR — cannot decide

  residual_dupe (pair-based, from residual_name_dupes / same_chain_close):
      MERGE   — same POI
      DISTINCT — different POIs sharing a name/coord
      UNCLEAR — cannot decide

Callers wire `verdict_fn` to an actual LLM call. The reference
signatures below show the expected shape.
"""
from typing import Callable, Iterable


# ---------- Reference signatures ----------

def verdict_single_placeholder(place_ctx: dict) -> tuple:
    """Reference signature for a single-POI verdict (short_name /
    placeholder_name / name==address / chain_cat_mismatch).

    Returns (label, reason) where label depends on the candidate type
    (see module docstring)."""
    raise NotImplementedError("Wire this to your LLM client.")


def verdict_pair_placeholder(place_a_ctx: dict, place_b_ctx: dict) -> tuple:
    """Reference signature for a pair verdict (residual_dupe).

    Returns ("MERGE" | "DISTINCT" | "UNCLEAR", reason)."""
    raise NotImplementedError("Wire this to your LLM client.")


# ---------- Batch helpers ----------

def batch_single_verdict(candidates: Iterable[dict],
                        verdict_fn: Callable) -> list:
    """Apply `verdict_fn(candidate) -> (label, reason)` per candidate,
    where each `candidate` is a dict describing a single POI with the
    full context needed for reasoning (name, category, address, chain,
    coords, website, phone, external_ids). Returns a new list with
    `verdict` + `reason` attached.
    """
    out = []
    for c in candidates:
        label, reason = verdict_fn(c)
        row = dict(c)
        row["verdict"] = label
        row["reason"] = reason
        out.append(row)
    return out


def batch_pair_verdict(pairs: Iterable[dict], verdict_fn: Callable) -> list:
    """Apply `verdict_fn(pair) -> (label, reason)` per pair, where each
    `pair` describes both POIs and their similarity signals."""
    out = []
    for p in pairs:
        label, reason = verdict_fn(p)
        row = dict(p)
        row["verdict"] = label
        row["reason"] = reason
        out.append(row)
    return out


# ---------- Post-verdict split helpers ----------

def split_by_verdict(verdicts, key="verdict"):
    """Group verdicts by their label. Returns dict[label -> list]."""
    out = {}
    for v in verdicts:
        out.setdefault(v.get(key), []).append(v)
    return out


def delete_ids(verdicts, delete_labels=("DELETE",)):
    """From a list of single-POI verdicts, return the list of place_ids
    with a DELETE-like label — safe to pass to
    `act.delete_from_sample_places`."""
    return [v["place_id"] for v in verdicts
            if v.get("verdict") in delete_labels]


def merge_pairs(verdicts, merge_label="MERGE"):
    """From a list of pair verdicts, return (id_a, id_b) tuples labeled
    MERGE — safe to pass to `act.write_merge_pair_csv`."""
    return [(v["id_a"], v["id_b"]) for v in verdicts
            if v.get("verdict") == merge_label]


def unchain_ids(verdicts, unchain_label="UNCHAIN"):
    """From chain-cat mismatch verdicts, return place_ids that should
    have chain_id set to null via observations."""
    return [v["place_id"] for v in verdicts
            if v.get("verdict") == unchain_label]
