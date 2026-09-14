# Methodology — DARC form ↔ Linear ↔ schema ↔ canonical reconciliation

Fourth-line defense against silent scope / schema drift. Runs before delivery and again after any post-canonical remediation.

## Four surfaces per sample

Every sample has four "sources of truth" that must agree. When they don't, the client sees one thing and the operator worked from another.

1. **Linear ticket (PS-XXX)** — the customer's stated ask: brands, geography, requested attributes, deadline.
2. **DARC form (Google Sheet)** — operator-side spec, one Google Sheet per sample_criteria: summary tab (customer, brands, boundary), delivery schema tab (column list + notes), and a Canonical Check tab that tracks known-pending validations.
3. **`samples.schema` JSONB** — what the export pipeline actually emits (label → attribute pairs, one per column).
4. **`checks/canonical_check.json` in S3** — sample-forge's `--canonical-check` audit record: LLM-produced findings per run, with `critical / warning / ok` counts.

## Three checks

- `darc_vs_ticket` — did the sample scope drift after the ticket was signed off? Widened brands, changed geography, quiet attribute swaps.
- `darc_vs_schema` — is what the DARC lists in the delivery-schema tab actually what the export emits? Every DARC column should appear in `samples.schema.fields`; every schema field should appear in the DARC.
- `canonical_check` — does the Canonical Check tab (pending validations the operator recorded) match what sample-forge's `canonical_check.json` shows as active vs resolved?

## LLM verdict per issue

Every axis of every check goes through a per-issue LLM verdict:

- **AGREE** — surfaces match, no action.
- **DIVERGE_SILENT** — surfaces differ and neither side knows. Escalate.
- **DIVERGE_INTENTIONAL** — one side was intentionally updated (e.g. operator narrowed brand list after client conversation) but the other wasn't synced. Note in delivery + update the lagging surface.
- **UNCLEAR** — cannot resolve; escalate to operator.

Sample-forge's own Linear cross-check already runs one axis of this on every `run-pipeline` (records AGREE / DISAGREE with critical + warning counts per PS-XXX). This module complements it by adding the DARC form dimension and the canonical-check reconciliation.

## Empirical on sample 9990

- **Ticket** (PS-888): CPG competitive-evaluation, Makati or BGC boundary, "special categories: all", no explicit visitation ask.
- **DARC form** (spreadsheet_id `1mEg-Y2G-PnkxTIpW_iX_Aq3GpLUBD_yv5isTraBUVmA`): matches ticket scope.
- **`samples.schema`**: 61 fields, no `estimated_visits_monthly` column emitted — matches the ticket's no-visits ask.
- **`canonical_check.json`**: final delivered run had 0 critical, 5 warning (all systemic Dataplor ingest patterns).

Result across all four surfaces: AGREE. Linear cross-check output confirmed: `AGREE — PS-888: 0 critical / 4 warning`. Delivered.
