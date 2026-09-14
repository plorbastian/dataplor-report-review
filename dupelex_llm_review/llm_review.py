"""Phase 3 — LLM POI-por-POI review of the medium tier.

The medium tier is what the guards leave ambiguous: signals are mixed, name
is close-but-not-identical, coords are close but not zero. This step is
NOT a rules engine. Each pair is evaluated with full context (name intent,
address specificity, category, brand, coordinates, external IDs, chain
membership, provisional flag) and one of three verdicts is emitted:

  MERGE     — same POI, same real-world intent
  DISTINCT  — different POIs (different practitioners, different ATMs,
              different tenants sharing an address, different brands)
  UNCLEAR   — cannot decide with confidence → leave in DB unchanged

The verdict comes from a reasoning agent that reads the full pair record.
This module exposes a `verdict_pair(pair)` interface that a caller can
implement against Claude, GPT, or any inline-reasoning LLM. It also
provides two convenience helpers:

  - `bulk_string_exact_promotion(medium)`: fast pre-pass that promotes
    obvious dupes (identical normalized name + same address + same
    category) out of medium before the LLM runs — Google's tokenizer
    can wildly mis-score `name_similarity` on identical strings, so we
    trust string equality first.
  - `apply_verdicts(medium, verdicts)`: merges the verdict dict back
    into the tiered structure.
"""

from typing import Callable, Iterable


def _norm(s):
    return " ".join((s or "").lower().split())


def bulk_string_exact_promotion(medium):
    """Pre-pass over the medium tier. Promotes pairs where the normalized
    name matches exactly AND the same category holds. Returns
    (still_medium, promoted_auto, promoted_high).
      - same name + same cat + same address prefix -> auto
      - same name + same cat (any address)         -> high
    """
    auto, high, still = [], [], []
    for p in medium:
        n1 = _norm(p.get("p1_name"))
        n2 = _norm(p.get("p2_name"))
        a1 = _norm(p.get("p1_addr"))
        a2 = _norm(p.get("p2_addr"))
        same_cat = p.get("p1_cat") == p.get("p2_cat")
        exact_name = (n1 == n2) and bool(n1)
        exact_addr = (a1 == a2) and bool(a1)

        if exact_name and same_cat and exact_addr:
            p["reason"] = "string-exact name+addr+cat"
            auto.append(p)
        elif exact_name and same_cat:
            p["reason"] = "string-exact name + same cat (diff addr)"
            high.append(p)
        else:
            still.append(p)
    return still, auto, high


def apply_verdicts(medium, verdicts):
    """Attach a verdict + reason to each pair in `medium`. `verdicts` is
    a dict keyed by (place1_id, place2_id) tuple -> (label, reason).
    Returns the same list mutated for chaining.
    """
    for p in medium:
        key = (int(p["place1_id"]), int(p["place2_id"]))
        v = verdicts.get(key) or verdicts.get((key[1], key[0]))
        if v:
            p["verdict"], p["verdict_reason"] = v
    return medium


def merge_pairs_from_tiers(tiers):
    """Consolidate auto_accept + high_conf + medium(MERGE) into one list
    of merge pairs suitable for Phase 4 push."""
    merges = list(tiers.get("auto_accept", []))
    merges.extend(tiers.get("high_conf", []))
    merges.extend([p for p in tiers.get("medium", []) if p.get("verdict") == "MERGE"])
    return merges


# ---- Interface hint for the LLM caller ----

def verdict_pair_placeholder(pair) -> tuple:
    """Reference signature for an inline-LLM verdict function.

    The real implementation should send the pair record to the LLM with
    a prompt that requires per-POI reasoning (not pattern matching), then
    parse a MERGE/DISTINCT/UNCLEAR response.

    Return (label, reason) where label is one of "MERGE"/"DISTINCT"/"UNCLEAR".
    """
    raise NotImplementedError("Wire this to your LLM client.")


def batch_verdict(pairs: Iterable, verdict_fn: Callable) -> dict:
    """Apply `verdict_fn(pair) -> (label, reason)` over an iterable of pairs.
    Returns dict keyed by (id1, id2) tuple -> (label, reason).
    """
    out = {}
    for p in pairs:
        label, reason = verdict_fn(p)
        out[(int(p["place1_id"]), int(p["place2_id"]))] = (label, reason)
    return out
