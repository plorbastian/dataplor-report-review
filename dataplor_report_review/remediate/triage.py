"""Read canonical_check.json + triage each finding via LLM.

Verdicts:

  FIXABLE_NOW    per-POI observation write can clear this finding
                 examples: open_closed_status contradiction on N POIs;
                 phone number obviously wrong; category clearly wrong.

  SYSTEMIC       mass ingest / scraper bug that hits thousands of rows.
                 Fixing per POI is not viable; escalate to Dataplor's DQ.
                 examples: close-time encoding bug on 4K rows across all
                 weekdays; historical_popularity_scores populated before
                 opened_on for 2K POIs.

  DELIVERY_NOTE  don't fix upstream; call it out in the delivery
                 narrative and let the client decide.
                 examples: a legitimate outlier the client should know
                 about, a policy-level DQ choice.

  IGNORE         false positive; nothing to do.
"""
import json
from typing import Callable


def load_findings(canonical_check_json_path):
    """Load canonical_check.json and return the findings of the latest run."""
    d = json.load(open(canonical_check_json_path, encoding="utf-8"))
    runs = d.get("runs", [])
    if not runs:
        return []
    return runs[-1].get("findings", [])


def triage_finding_placeholder(finding: dict, sample_ctx: dict) -> tuple:
    """Reference signature for the LLM triage function.

    Args:
      finding: one row from canonical_check.json findings (has 'level',
               'check', 'summary', 'affected_ids' or similar).
      sample_ctx: {sample_id, customer, use_case, delivery_deadline, ...}

    Returns (label, reason) with label in {FIXABLE_NOW, SYSTEMIC,
    DELIVERY_NOTE, IGNORE}.
    """
    raise NotImplementedError("Wire this to your LLM client.")


def batch_triage(findings, sample_ctx, verdict_fn: Callable) -> list:
    """Apply LLM verdict per finding. Returns list of {finding, label, reason}."""
    out = []
    for f in findings:
        label, reason = verdict_fn(f, sample_ctx)
        out.append({"finding": f, "label": label, "reason": reason})
    return out


def fixable_findings(triaged):
    return [t for t in triaged if t["label"] == "FIXABLE_NOW"]


def systemic_findings(triaged):
    return [t for t in triaged if t["label"] == "SYSTEMIC"]


def delivery_note_findings(triaged):
    return [t for t in triaged if t["label"] == "DELIVERY_NOTE"]
