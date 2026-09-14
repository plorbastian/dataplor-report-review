"""DARC form ↔ Linear ticket congruence.

Fetch the DARC form's summary fields (customer, brand list, geography,
requested attributes) and the Linear ticket's stated scope (from title,
description, comments). LLM inline reasoning per axis decides whether
they match or diverge.

Divergences we care about:

  scope_narrowed     — the ticket asks for 5 brands but the DARC
                       lists 3. Either the operator narrowed the ask
                       (should note why in the DARC) or forgot two.

  scope_widened      — the DARC lists brands or geos not in the ticket.
                       This is common when the client expanded scope
                       verbally after the ticket was created; the DARC
                       should reflect the update but the ticket often
                       stays behind. Not a bug per se, worth flagging
                       for delivery narrative.

  geography_changed  — the ticket says "Metro Manila" but the DARC's
                       boundary is `R123456` (a smaller municipality).
                       Deliverable will have less coverage than the
                       ticket implies.

  attributes_changed — the DARC's "requested attributes" tab differs
                       from what the ticket originally asked for (e.g.
                       ticket asked for visits + trade areas, DARC only
                       has visits). Client expectation mismatch.
"""
from typing import Callable


def fetch_darc_summary(sheets_client, darc_sheet_url) -> dict:
    """Read the summary tab of the DARC form. Returns a dict with
    customer, brands, geography, attributes, etc.

    Callers supply their own Google Sheets client (googleapiclient or
    gspread). This module deliberately does not couple to a specific
    client to keep the dependency footprint small.
    """
    raise NotImplementedError("Wire this to your Google Sheets client.")


def fetch_ticket_scope(linear_client, ticket_id) -> dict:
    """Read the Linear ticket (PS-XXX) via GraphQL and return its
    stated scope. Callers supply a Linear GraphQL client."""
    raise NotImplementedError("Wire this to your Linear client.")


def compare_scope(darc: dict, ticket: dict, verdict_fn: Callable) -> list:
    """LLM inline per axis. Returns a list of findings, each dict with
    keys axis, darc_value, ticket_value, verdict, reason."""
    axes = ("customer", "brands", "geography", "attributes")
    out = []
    for axis in axes:
        dv = darc.get(axis)
        tv = ticket.get(axis)
        label, reason = verdict_fn(axis, dv, tv)
        out.append({
            "axis": axis, "darc_value": dv, "ticket_value": tv,
            "verdict": label, "reason": reason,
        })
    return out
