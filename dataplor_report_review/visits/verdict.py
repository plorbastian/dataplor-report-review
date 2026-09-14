"""LLM verdict per POI in the Javaria set.

Given a chained POI whose category isn't in the brand's core_1/core_2
lists, and given the customer's stated use case, the LLM decides:

  ACCEPT_STRIP  — losing visits for this POI is fine. Either the POI
                  genuinely fits an edge category the brand marks as
                  non-core (a BDO "corporate_office" branch when the
                  brand only cares about branch banking visits), or
                  the POI is a mis-classification the client won't act
                  on anyway.

  DELIVERY_GAP  — losing visits IS relevant to the client. Options:
                  a. Re-categorize the POI so its `business_category_id`
                     lands in `core_1_category_ids` (fix at the source).
                  b. Add the POI's category to the brand's
                     `core_1_category_ids` list (fix at the brand).
                  c. Drop the POI from the sample.
                  d. Keep the POI and flag it in the delivery note.

  UNCLEAR       — needs operator review.

The verdict function receives both the POI context AND the brand's
category configuration, so it can reason about *why* the mismatch
exists (e.g. "BDO's core_1 is
[bank, atm] but this POI is categorized as `corporate_office` — is that
a real head-office row that should stay non-core, or a mis-classified
branch that should be a `bank`?").
"""
from typing import Callable


def verdict_pattern_placeholder(place_ctx: dict, brand_ctx: dict, use_case: str) -> tuple:
    """Reference signature for the LLM verdict function.

    Args:
      place_ctx: {id, name, business_category_id, chain_id, address, ...}
      brand_ctx: {chain_id, core_1_category_ids, core_2_category_ids,
                  business_category_ids, name, primary_category, ...}
      use_case: free-text description of what the customer wants
                (e.g. "Red Bull retail audit in Metro Manila — need
                point-of-sale visitation for beverage placement").

    Returns (label, reason) with label in {ACCEPT_STRIP, DELIVERY_GAP, UNCLEAR}.
    """
    raise NotImplementedError("Wire this to your LLM client.")


def batch_verdict(javaria_rows, brand_ctx_by_chain, use_case: str,
                  verdict_fn: Callable):
    """Apply verdict per POI. Returns list of verdict dicts."""
    out = []
    for pid, name, cat, chain, has_visits in javaria_rows:
        place_ctx = {
            "id": pid, "name": name,
            "business_category_id": cat, "chain_id": chain,
        }
        bctx = brand_ctx_by_chain.get(chain, {})
        label, reason = verdict_fn(place_ctx, bctx, use_case)
        out.append({
            "id": pid, "name": name, "category": cat, "chain": chain,
            "verdict": label, "reason": reason,
        })
    return out


def delivery_gap_ids(verdicts):
    return [v["id"] for v in verdicts if v.get("verdict") == "DELIVERY_GAP"]


def accept_strip_ids(verdicts):
    return [v["id"] for v in verdicts if v.get("verdict") == "ACCEPT_STRIP"]
