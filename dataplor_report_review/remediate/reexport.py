"""Decide whether the delivered CSV needs a fresh place_export after
applying fixes, then trigger it via api.dataplor.com.

Decision rules (LLM inline, per fix batch):

  YES re-export when:
    - the fix changes a column the customer will read (open_closed_status,
      chain_id, category, name, address, coordinates, visitation).
    - the fix removes rows the client would otherwise see as garbage
      (numeric names, name==address, empty core fields).
    - the fix count is > 5 POIs or > 0.01% of the sample (visible impact).

  NO re-export when:
    - the fix affects only internal DB columns that the export doesn't
      emit (e.g. an internal quality flag).
    - the fix affects fewer than a handful of POIs AND the client already
      accepted the delivery with a note.
    - the fix is on a column that post-export re-derives from other
      fields (in which case a re-run of run-pipeline against the SAME
      export is enough — no fresh export_job needed).

The rule of thumb: if the customer would notice the fix in the CSV,
re-export.
"""
import json
import time
from typing import Callable

import urllib.request


EXPORT_JOB_ENDPOINT = "https://api.dataplor.com/v3/admin/export_jobs"
CONTAINER_TASK_ENDPOINT = "https://api.dataplor.com/v3/admin/container_tasks/{task_id}"


def decide_reexport_placeholder(fixed_rows: list, sample_ctx: dict) -> tuple:
    """Reference signature for the LLM re-export decision.

    Args:
      fixed_rows: the observation rows that were applied.
      sample_ctx: {sample_id, customer, use_case, rows_delivered, ...}

    Returns (need_reexport: bool, reason: str).
    """
    raise NotImplementedError("Wire this to your LLM client.")


def trigger_export_job(api_auth_token, api_email, sample_id, timeout_s=1800):
    """Fire a fresh place_export via api.dataplor.com and poll to
    completion. Returns the export record.
    """
    headers = {
        "Authorization": f'Token token="{api_auth_token}", email="{api_email}"',
        "Content-Type": "application/json",
    }
    payload = json.dumps({"sample_id": sample_id, "export_type": "place_export"}).encode()
    req = urllib.request.Request(EXPORT_JOB_ENDPOINT, data=payload, headers=headers)
    with urllib.request.urlopen(req) as r:
        resp = json.loads(r.read())
    task_id = resp.get("container_task_id") or resp.get("id")

    deadline = time.time() + timeout_s
    while time.time() < deadline:
        req = urllib.request.Request(
            CONTAINER_TASK_ENDPOINT.format(task_id=task_id),
            headers=headers,
        )
        with urllib.request.urlopen(req) as r:
            status = json.loads(r.read())
        state = status.get("status") or status.get("state")
        if state in ("succeeded", "completed"):
            return status
        if state in ("failed", "error"):
            raise RuntimeError(f"export_job {task_id} failed: {status}")
        time.sleep(10)
    raise TimeoutError(f"export_job {task_id} timed out after {timeout_s}s")


# ---------- Convenience: full remediate flow ----------

def full_flow(canonical_json_path, sample_ctx, triage_fn, decide_fn,
              write_obs, run_obs, run_pipeline):
    """
    Orchestrate the whole remediate cycle. Each callable is wired by
    the caller so the module stays free of Dataplor infra imports.

    triage_fn(finding, sample_ctx) → (label, reason)
    decide_fn(fixed_rows, sample_ctx) → (need_reexport, reason)
    write_obs(rows, csv_path)
    run_obs(csv_path)                     — applies observations + PTU
    run_pipeline(sample_id, use_existing_export=bool)
                                          — sample-forge run-pipeline
    """
    from .triage import load_findings, batch_triage, fixable_findings

    findings = load_findings(canonical_json_path)
    triaged = batch_triage(findings, sample_ctx, triage_fn)
    fixables = fixable_findings(triaged)

    all_rows = []
    for f in fixables:
        # The LLM produces the concrete observation rows for each finding.
        # Delegate to the caller — this module doesn't know the mapping.
        all_rows.extend(f.get("observation_rows", []))

    if not all_rows:
        return {"triaged": triaged, "reexport": False,
                "reason": "no FIXABLE_NOW findings produced observations"}

    csv_path = sample_ctx["obs_csv_path"]
    write_obs(all_rows, csv_path)
    run_obs(csv_path)

    need, reason = decide_fn(all_rows, sample_ctx)
    if need:
        # Trigger new place_export + re-run post-export
        run_pipeline(sample_ctx["sample_id"], use_existing_export=False)
    return {"triaged": triaged, "applied": len(all_rows),
            "reexport": need, "reason": reason}
