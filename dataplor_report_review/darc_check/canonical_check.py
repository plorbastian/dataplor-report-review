"""Canonical Check tab reader + sample-forge validation cross-reference.

The DARC form's Canonical Check tab tracks known-pending validations
(fill-rate anomalies, column-coverage gaps, glossary mismatches).
Sample-forge's `--canonical-check` flag records its own JSON at
`s3://.../checks/canonical_check.json` on every pipeline run.

Both should agree: every pending item on the sheet should either
(a) be resolved by the latest sample-forge run and marked done on the
sheet, or (b) still show as an active finding in the JSON. Sheet items
that are neither resolved nor active are stale and cause operator
confusion.
"""
import json


CANONICAL_CHECK_TAB_URL = (
    "https://docs.google.com/spreadsheets/d/"
    "1mEg-Y2G-PnkxTIpW_iX_Aq3GpLUBD_yv5isTraBUVmA/edit"
)


def fetch_canonical_tab(sheets_client, sheet_url=CANONICAL_CHECK_TAB_URL,
                        sample_id=None) -> list:
    """Return the Canonical Check tab rows filtered to the given
    sample_id. Each row: {sample_id, check, status, notes, ...}."""
    raise NotImplementedError("Wire this to your Google Sheets client.")


def fetch_sf_canonical_json(s3_client, sample_id, criteria_id, bucket="dataplor-data") -> dict:
    """Read sample-forge's checks/canonical_check.json for a sample."""
    key = f"post_export/samples/criteria_{criteria_id}/sample_{sample_id}/checks/canonical_check.json"
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return json.loads(obj["Body"].read())


def cross_reference(tab_rows: list, sf_json: dict, verdict_fn) -> list:
    """LLM inline per row: is this pending sheet check reflected in the
    sample-forge JSON (still active / already resolved) or stale?

    Returns list of {check, sheet_status, sf_status, verdict, reason}.
    """
    sf_findings = {f.get("check"): f for f in sf_json.get("findings", [])}
    out = []
    for row in tab_rows:
        check = row.get("check")
        sf_state = "active" if check in sf_findings else "not_in_sf_run"
        label, reason = verdict_fn(row, sf_findings.get(check))
        out.append({
            "check": check,
            "sheet_status": row.get("status"),
            "sf_status": sf_state,
            "verdict": label,
            "reason": reason,
        })
    return out
