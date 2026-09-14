"""End-to-end walkthrough of the seven-layer flow on DataPlor sample 9990
(Red Bull PH, Makati boundary, competitive-evaluation).

This is a NARRATIVE + CODE SCAFFOLD, not a runnable one-shot. Each phase
prints what it did and hands off to the next; the LLM verdict functions
are left as placeholders — wire them to your inline-reasoning client.
"""
import os
import psycopg2

# --------------------------------------------------------------------- 1. dupelex
from dataplor_report_review.dupelex import (
    filter as dup_filter,
    enrich as dup_enrich,
    guard as dup_guard,
    reguard as dup_reguard,
    llm_review as dup_llm,
    safety as dup_safety,
    strict as dup_strict,
    merge_push,
    sample_cleanup,
    verify as dup_verify,
)

# --------------------------------------------------------------------- 2. chain
from dataplor_report_review.chain import (
    filter as chain_filter,
    enrich as chain_enrich,
    llm_review as chain_llm,
    apply as chain_apply,
    verify as chain_verify,
)

# --------------------------------------------------------------------- 3. export_qa
from dataplor_report_review.export_qa import (
    checks as qa_checks,
    from_csv,
    components,
    verdict as qa_verdict,
    act as qa_act,
)

# --------------------------------------------------------------------- 4. visits
from dataplor_report_review.visits import (
    scan as visits_scan,
    verdict as visits_verdict,
    act as visits_act,
)

# --------------------------------------------------------------------- 5. congruence
from dataplor_report_review.congruence import (
    three_way_report,
)

# --------------------------------------------------------------------- 6. darc_check
from dataplor_report_review.darc_check import (
    darc_vs_ticket,
    darc_vs_schema,
    canonical_check,
)

# --------------------------------------------------------------------- 7. remediate
from dataplor_report_review.remediate import (
    triage,
    fix,
    reexport,
)


SAMPLE_ID = 9990
CRITERIA_ID = 39995
CUSTOMER_USE_CASE = (
    "Red Bull Philippines competitive-evaluation sample: general POI "
    "coverage across all business types in the Makati boundary. No "
    "explicit visitation ask; popularity + sentiment history are enough."
)


def get_read():
    return psycopg2.connect(
        host=os.environ["DB_READ_HOST"], dbname=os.environ["DB_READ_NAME"],
        user=os.environ["DB_READ_USER"], password=os.environ["DB_READ_PASSWORD"],
    )


def get_prod():
    return psycopg2.connect(
        host=os.environ["DB_PROD_HOST"], dbname=os.environ["DB_PROD_NAME"],
        user=os.environ["DB_PROD_USER"], password=os.environ["DB_PROD_PASSWORD"],
    )


# ==== phase 1: dupelex — pair review + safety filters + merge push =========
# Filter the raw dupelex CSV.gz to actionable pairs, enrich with places
# context, tier via guards, LLM-review the medium tier, apply safety
# filters, push confirmed merges via matches:process, delete children
# from sample_places.


# ==== phase 2: chain — apply chain_id to unchained POIs ====================
# Load the chain report, filter to rank-1 unchained candidates >= 0.5
# score, enrich with brand context, LLM-verdict per POI, write
# /chain_id observations via mass_observations.py.


# ==== phase 3: export_qa — post-cleanup DQ against the delivered CSV =======
# WIDEN via checks.py, NARROW via verdict.py, APPLY via act.py.
# Includes the LATIN-only garbage-name check that PRESERVES foreign-
# language scripts (Hebrew, Arabic, Devanagari, Tamil, CJK, Thai).


# ==== phase 4: visits — Javaria pattern ===================================
# Surfaces chained POIs whose category is outside brand.core_1 /
# core_2 lists. LLM per-POI decides whether the strip is a delivery
# gap or acceptable.


# ==== phase 5: congruence — three-way DB ↔ export ↔ post-export ============
# Row counts, UUID coverage, no leaked children, no phantom rows,
# defensible column strips.


# ==== phase 6: darc_check — DARC ↔ ticket ↔ schema ↔ canonical =============
# Reconcile the four surfaces. sample-forge's --canonical-check flag
# writes checks/canonical_check.json; sample-forge's Linear cross-check
# covers ticket vs criteria.


# ==== phase 7: remediate — canonical findings loop ========================
# Load canonical_check.json → LLM triage per finding → apply fixes for
# FIXABLE_NOW → decide whether a fresh place_export is needed → hand
# off to run-pipeline again on the new export.
