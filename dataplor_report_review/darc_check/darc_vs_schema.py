"""DARC form ↔ samples.schema congruence.

The DARC form has a "delivery schema" tab (column list, types, notes).
The DB has a `samples.schema` JSONB per sample. They should agree.

Common gaps:
  - the operator widened `samples.schema` mid-project (adding a column
    like `dataplor_status`) but forgot to update the DARC tab.
  - conversely, the DARC lists a column the current schema doesn't
    emit (deprecated field).
  - column ORDER differs — DARC drives client expectations, so if the
    export emits columns in a different order the delivery narrative
    should note it.
"""
import json


def fetch_darc_schema_tab(sheets_client, darc_sheet_url) -> list:
    """Return the DARC "delivery schema" tab as a list of dicts
    (one per column: {name, type, notes})."""
    raise NotImplementedError("Wire this to your Google Sheets client.")


def fetch_sample_schema(read_conn, sample_id) -> dict:
    """Return the samples.schema JSONB for the sample."""
    with read_conn.cursor() as c:
        c.execute("SELECT schema FROM samples WHERE id = %s", (sample_id,))
        row = c.fetchone()
    if not row:
        return {}
    schema = row[0]
    if isinstance(schema, str):
        schema = json.loads(schema)
    return schema or {}


def compare(darc_cols, db_schema, verdict_fn) -> list:
    """Diff DARC columns vs samples.schema fields, LLM inline per
    discrepancy. Returns list of findings."""
    darc_names = {c["name"] for c in darc_cols}
    schema_fields = {f.get("name") or f.get("key") for f in db_schema.get("fields", [])}
    findings = []
    for col in darc_names - schema_fields:
        label, reason = verdict_fn("darc_extra", col)
        findings.append({"issue": "in_darc_not_in_schema", "column": col,
                         "verdict": label, "reason": reason})
    for col in schema_fields - darc_names:
        label, reason = verdict_fn("schema_extra", col)
        findings.append({"issue": "in_schema_not_in_darc", "column": col,
                         "verdict": label, "reason": reason})
    return findings
