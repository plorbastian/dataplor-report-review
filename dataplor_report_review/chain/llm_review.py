"""Chain LLM POI-por-POI verdict.

For each unchained candidate emitted by `filter.actionable_unchained`,
the LLM must decide whether the POI actually belongs to the candidate
`chain_id`. This is NOT a rules engine — the operator directive is that
the LLM reads brand + POI context and reasons per-POI:

  - Does the POI's name match the brand name / one of its aliases?
  - Is the POI's business_category compatible with the brand's
    allowed_categories (and NOT in banned_categories)?
  - Does the POI's website root match the brand's website_root?
  - Does the country match the brand's country_code?
  - If the brand name is a common surname or city name, is the POI
    actually the brand or just a namesake? (Chain analyzer FP mode.)

Verdicts:
  APPLY   — POI belongs to this brand; apply /chain_id observation
  SKIP    — POI does not belong; leave unchained
  UNCLEAR — cannot decide; leave unchained (safe default)

`verdict_pair_placeholder` shows the expected function signature. The
real implementation should call the LLM with the brand + POI record.
"""
from typing import Callable, Iterable


def verdict_pair_placeholder(place_ctx: dict, brand_ctx: dict, candidate: dict) -> tuple:
    """Reference signature: return (label, reason). Label is one of
    "APPLY" / "SKIP" / "UNCLEAR"."""
    raise NotImplementedError("Wire this to your LLM client.")


def batch_verdict(candidates: Iterable, places: dict, brands: dict,
                  verdict_fn: Callable) -> list:
    """Run `verdict_fn(place_ctx, brand_ctx, candidate)` over each
    candidate. Returns a list of {place_id, chain_id, verdict, reason}.
    """
    out = []
    for place_id, cand in candidates:
        pctx = places.get(place_id)
        brand_id = cand.get("chain_id")
        bctx = brands.get(brand_id, {})
        if not pctx:
            out.append({"place_id": place_id, "chain_id": brand_id,
                        "verdict": "SKIP", "reason": "place not in DB"})
            continue
        label, reason = verdict_fn(pctx, bctx, cand)
        out.append({
            "place_id": place_id,
            "chain_id": brand_id,
            "verdict": label,
            "reason": reason,
            "score": cand.get("score"),
        })
    return out


def apply_list(verdicts):
    """Return the subset with verdict=='APPLY' — ready for observation write."""
    return [v for v in verdicts if v.get("verdict") == "APPLY"]
