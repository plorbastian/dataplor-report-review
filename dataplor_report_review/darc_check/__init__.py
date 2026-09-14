"""darc_check — validate the DARC form of a sample against Linear + schema.

The DARC form (Sample Definition Request And Confirmation) is a Google
Sheet the operator fills out per sample. It carries the customer-facing
column names, requested attributes, any category/geo constraints, and
a Canonical Check tab that tracks known-pending validations for the
sample.

Three congruence checks per sample:

  darc_vs_ticket    — the DARC form's stated scope must agree with the
                      Linear ticket (PS-XXX) that requested the sample.
                      Discrepancies: brand list mismatch, geography
                      changed post-ticket, column set widened.

  darc_vs_schema    — the DARC form's "delivery schema" tab must agree
                      with `samples.schema` (JSONB in the DB). If the
                      schema was widened after the DARC was signed off
                      but not written back, the delivered CSV shape may
                      surprise the client.

  canonical_check   — read the DARC form's Canonical Check tab (open
                      pending checks) and cross-reference against what
                      sample-forge's `--canonical-check` validation
                      recorded. Any check pending on the sheet but
                      never resolved is a delivery risk.

Each check surfaces candidates; the LLM decides per-issue whether it's
a real gap or an artifact of a stale sheet cell. Patterns never approve
on their own.
"""
from . import darc_vs_ticket, darc_vs_schema, canonical_check

__all__ = ["darc_vs_ticket", "darc_vs_schema", "canonical_check"]
