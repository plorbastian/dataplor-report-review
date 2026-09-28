"""POI-por-POI verdict for a brand-heavy sample.

Given a POI (as loaded by `context.load_sample_pois`) and the brand_ctx
for its `chain_id`, accumulate positive and negative signals and issue
one of three verdicts:

  KEEP        — chain assignment looks correct
  FP_UNCHAIN  — chain assignment is wrong; the POI should have its
                `/chain_id` unset via an observation
  UNCLEAR     — signals mixed / insufficient; leave in DB unchanged and
                surface the pair to the operator

CANONICAL FIX for a category mismatch (per Javaria's `is_core` diagram):
if a POI is a real store of the brand but its
`business_category_id` is not among the brand's `business_category_ids`,
update the PLACE's category to match the brand — do NOT expand the
brand's list to swallow the odd category. The brand row should
represent what the brand actually IS, not accumulate every category
the platform happens to tag a store with.

Exception: a true sub-place (bakery inside a supermarket) legitimately
carries a different category from the parent brand and should keep it,
losing the parent brand's visitation on purpose. This module flags
those cases as `corporate_office` style carve-outs — the reviewer
decides whether to keep them in the sample.

Signal families:

  NAME
    +  POI name starts with, or contains as a clean token, one of the
       brand's name variants (`brand_ctx.names`).
    +  POI name matches a brand-specific accepted pattern (`Bara <colonia>`,
       `Super Bara <colonia>`, `Tienda 3B ...`, etc — brand-native
       naming captured in `_ACCEPT_NAME_PATTERNS`).
    -  POI name matches a known FP pattern for that brand
       (`_FP_NAME_PATTERNS`) — e.g. `Tiendas Bara Bara` fashion,
       `Neto Wings`, `Abarrotes Barajas`, `Departamento 3B`.

  CATEGORY
    +  cat in brand's `business_cats` — the only category signal that
       drives is_core / visits at export.
    -  cat is `corporate_office` — not a storefront but may be kept in
       the sample per operator decision.
    -  cat outside the brand's `business_cats` — the POI will lose
       visits at export unless the category is corrected.

  DOMAIN
    +  website contains a brand-owned domain from `brand_ctx.domains`
    -  website matches a known FP domain (`_FP_DOMAINS`)

  PROVISIONAL
    -  provisional=True — unverified import, does not by itself flip
       the verdict but lowers confidence

Verdict logic:

  strong_neg > 0                                    -> FP_UNCHAIN (high)
  strong_pos >= 2                                    -> KEEP (high)
  strong_pos == 1, no signals_neg                    -> KEEP (medium)
  strong_pos == 1, signals_neg == corporate_office   -> KEEP (medium)
  strong_pos == 1, other signals_neg                 -> UNCLEAR (low)
  no strong signals either way                       -> UNCLEAR (low)

"Strong positive" = brand-variant name match, brand-native name
pattern, official-domain website, or business_cats category. "Strong
negative" = FP name pattern or FP domain. Everything else contributes
but does not flip the verdict on its own.

Historical note: an earlier revision of this reviewer also inspected
`core_1_category_ids` and `core_2_category_ids`. Those fields on
`brands` are unused stale metadata (confirmed by their author in
September 2026) and were removed so the module reflects only signals
that actually drive the export path.

The rule table is a summariser, not the decider. Callers should read
`signals_pos` and `signals_neg` on each verdict and treat borderline
cases as a hand-off to an inline reasoning agent (human or LLM), same
convention as the rest of the repo.
"""
import re


# Brand-native naming patterns that a POI can match to be accepted even
# if it does not exactly contain one of `brand_ctx.names`. Keyed by
# chain_id.
_ACCEPT_NAME_PATTERNS = {
    "tiendas_bara": [
        r"^(super\s+)?bara\s+",
        r"^tiendas?\s+bara(\s|$)",
        r"^bara(\.|$)",
    ],
    "tiendas_3b": [
        r"\b3b\b",
        r"\btriple\s+b\b",
    ],
    "tiendas_neto": [
        r"^tiendas?\s+neto(\s|$)",
        r"^neto\s+\S{3,}",
    ],
}

# Known FP name patterns per brand — names that look like the brand but
# belong to a different chain or are a namesake collision. Add new ones
# as audits surface them.
_FP_NAME_PATTERNS = {
    "tiendas_bara": [
        r"\btiendas?\s+bara\s+bara\b",     # 'Tiendas Bara Bara' fashion chain
        r"\babarrotes?\s+barajas?\b",       # Barajas is a common surname
        r"\bbarbara\b",                     # name overlap
        r"\bbaratillo\b",                   # market name
    ],
    "tiendas_neto": [
        r"\bneto\s+wings?\b",
        r"\bneto\s+estilistas?\b",
        r"\bneto\s+morrones?\b",
    ],
    "tiendas_3b": [
        r"\b3b\s+diseno\b",
        r"\b3b\s+distribuidora\b",
        r"\bdepartamento\s+3b\b",
    ],
}

# Known FP domains per brand — websites that superficially resemble the
# brand's domain but belong to a different chain.
_FP_DOMAINS = {
    "tiendas_bara": [
        "tiendasbarabara.com.mx",
        "super-bara.com.mx",
    ],
    "tiendas_neto": [],
    "tiendas_3b": [],
}


def _name_matches_variant(name_lc, variants):
    """Return the first variant that matches at the start of the name
    or as a clean whole-word token; None if no match. `name_lc` is the
    POI name already lowercased."""
    for v in variants:
        vl = v.lower()
        if name_lc.startswith(vl):
            return v
        if re.search(rf"\b{re.escape(vl)}\b", name_lc):
            return v
    return None


def _name_matches_accept_pattern(name_lc, chain):
    for pat in _ACCEPT_NAME_PATTERNS.get(chain, []):
        if re.search(pat, name_lc):
            return pat
    return None


def _name_matches_fp_pattern(name_lc, chain):
    for pat in _FP_NAME_PATTERNS.get(chain, []):
        if re.search(pat, name_lc):
            return pat
    return None


def review_one(poi, brand_ctx_for_chain):
    """Verdict + reasoning for a single POI.

    Returns a dict:
      id, name, chain, cat, website,
      verdict ('KEEP' | 'FP_UNCHAIN' | 'UNCLEAR'),
      confidence ('high' | 'medium' | 'low'),
      signals_pos: list[str], signals_neg: list[str]

    `brand_ctx_for_chain` is the entry for `poi['chain']` from
    `context.load_brand_context()`. Passing `None` (brand row missing)
    yields UNCLEAR with a `no brand context` neg signal.
    """
    chain = poi["chain"]
    name = poi.get("name") or ""
    name_lc = name.lower()
    cat = poi.get("cat") or ""
    website = (poi.get("website") or "").lower()
    signals_pos = []
    signals_neg = []

    if not brand_ctx_for_chain:
        return {
            "id": poi["id"], "name": name, "chain": chain, "cat": cat,
            "website": poi.get("website") or "",
            "verdict": "UNCLEAR", "confidence": "low",
            "signals_pos": [],
            "signals_neg": [f"no brand context for chain {chain!r}"],
        }

    ctx = brand_ctx_for_chain

    # --- NAME ---
    variant_hit = _name_matches_variant(name_lc, ctx.get("names") or [])
    accept_hit = _name_matches_accept_pattern(name_lc, chain)
    if variant_hit:
        signals_pos.append(f"name contains brand variant {variant_hit!r}")
    elif accept_hit:
        signals_pos.append(f"name matches brand-native pattern /{accept_hit}/")
    fp_name_hit = _name_matches_fp_pattern(name_lc, chain)
    if fp_name_hit:
        signals_neg.append(
            f"name matches known FP pattern /{fp_name_hit}/ (namesake collision)"
        )

    # --- CATEGORY ---
    if cat and cat in (ctx.get("business_cats") or []):
        signals_pos.append(
            f"category {cat!r} is in brand.business_category_ids (is_core=true)"
        )
    elif cat == "corporate_office":
        signals_neg.append(
            "category is corporate_office (not a storefront)"
        )
    elif cat:
        signals_neg.append(
            f"category {cat!r} is outside brand.business_category_ids "
            "(is_core=false — visits would be stripped at export unless "
            "the place's category is updated to match the brand)"
        )
    else:
        signals_neg.append("category is missing")

    # --- DOMAIN ---
    if website:
        matched_official = None
        for dom in ctx.get("domains") or []:
            if dom and dom.lower() in website:
                matched_official = dom
                break
        if matched_official:
            signals_pos.append(
                f"website contains official brand domain {matched_official!r}"
            )
        else:
            for fp_dom in _FP_DOMAINS.get(chain, []):
                if fp_dom in website:
                    signals_neg.append(
                        f"website contains FP domain {fp_dom!r}"
                    )
                    break

    # --- PROVISIONAL ---
    if poi.get("provisional"):
        signals_neg.append("provisional=true (unverified import)")

    # --- VERDICT ---
    def _is_strong_pos(s):
        return any(k in s for k in
                   ("brand variant", "official brand domain",
                    "business_category_ids", "brand-native pattern"))

    def _is_strong_neg(s):
        return "FP pattern" in s or "FP domain" in s

    strong_pos = sum(1 for s in signals_pos if _is_strong_pos(s))
    strong_neg = sum(1 for s in signals_neg if _is_strong_neg(s))
    only_neg_is_corp = (
        len(signals_neg) == 1
        and signals_neg[0].startswith("category is corporate_office")
    )

    if strong_neg > 0:
        verdict, confidence = "FP_UNCHAIN", "high"
    elif strong_pos >= 2:
        verdict, confidence = "KEEP", "high"
    elif strong_pos == 1 and not signals_neg:
        verdict, confidence = "KEEP", "medium"
    elif strong_pos == 1 and only_neg_is_corp:
        verdict, confidence = "KEEP", "medium"
    elif strong_pos == 1:
        verdict, confidence = "UNCLEAR", "low"
    else:
        verdict, confidence = "UNCLEAR", "low"

    return {
        "id": poi["id"], "name": name, "chain": chain, "cat": cat,
        "website": poi.get("website") or "",
        "verdict": verdict, "confidence": confidence,
        "signals_pos": signals_pos, "signals_neg": signals_neg,
    }


def review_pois(pois, brand_ctx):
    """Run `review_one` over an iterable of POI dicts.

    Returns a list preserving input order. `brand_ctx` is the dict
    returned by `context.load_brand_context()`.
    """
    return [review_one(p, brand_ctx.get(p.get("chain"))) for p in pois]


def summarise(verdicts):
    """Small counter over a verdict list, useful for logging + tests."""
    out = {"KEEP": 0, "FP_UNCHAIN": 0, "UNCLEAR": 0,
           "high": 0, "medium": 0, "low": 0}
    for v in verdicts:
        out[v["verdict"]] += 1
        out[v["confidence"]] += 1
    return out
