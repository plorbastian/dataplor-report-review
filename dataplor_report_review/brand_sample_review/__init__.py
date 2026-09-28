"""brand_sample_review — POI-por-POI review for brand-heavy samples.

The other layers in this repo (dupelex, chain, export_qa, visits) were
built for general samples where each POI may belong to a different brand
and only POIs flagged by a pattern check ever reach the LLM. That
design does not fit a `brand_audit` sample, where the entire sample
comes from one or a small set of brands, every POI is expected to be
that brand, and the operator wants a per-POI LLM check with the brand's
own context — even for POIs no pattern check would ever surface.

This module is the standalone Stage C-synthetic gate:

  context — pull brand_ctx (core_1 / core_2 / business_cats / domains /
            name variants) from the DB for the brands in the sample.
  review  — POI-por-POI verdict against brand_ctx with reasoning
            documented per POI. Returns KEEP / FP_UNCHAIN / UNCLEAR with
            per-POI signals_pos / signals_neg lists and a confidence
            level (high / medium / low).
  apply   — emit ``/chain_id`` unchain observations for FP_UNCHAIN
            verdicts (`type='ManualObservation'`) and trigger Kuebiko
            PTU via Fargate. Idempotent.

Design notes:

- The verdict is NOT purely rules-based. The rules in `review` compute
  signal strengths (name match, category tier, domain match, provisional
  flag, known FP name patterns). A wrapping reasoning agent — human or
  LLM — reads the accumulated signals per POI and issues the verdict.
  This mirrors the repo-wide convention that patterns filter and an
  agent decides.

- FP name patterns and FP domains per brand are the fastest way to
  encode brand-specific known collisions ('Tiendas Bara Bara' fashion,
  'Neto Wings', 'Abarrotes Barajas', 'Departamento 3B'). Add new
  patterns to `_FP_NAME_PATTERNS` / `_FP_DOMAINS` in `review.py` as
  each audit surfaces them.

- The gate assumes chain_id is already applied. It reviews whether that
  chain assignment is correct, not whether an untagged POI should be
  tagged (for that, use `chain.llm_review`).
"""
from . import context, review, apply
from .context import InvalidCategoryError

__all__ = ["context", "review", "apply", "InvalidCategoryError"]
