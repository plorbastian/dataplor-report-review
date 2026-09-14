# Methodology — canonical-check remediation

Post-delivery loop that reads sample-forge's `canonical_check.json`, applies the fixes the LLM decides are fixable per-POI, and — if the fixes are customer-visible — triggers a fresh `place_export` + `run-pipeline` so the delivered CSV reflects the corrections.

## Three-verdict triage

Every canonical-check finding falls into one of four buckets. The LLM decides per finding using both the finding text and the customer's use case:

- **FIXABLE_NOW** — the finding names N specific POIs (usually via `dpids` or `affected_ids`) and points to a column that a per-POI observation write can correct. Example: 3 POIs marked `open_closed_status = "opening soon"` while `opened_on ≤ today` → write `/open_status = "open"` + `/opening_soon = false` + `/temporarily_closed = false` for those 3.
- **SYSTEMIC** — the finding covers thousands of rows and points to a scraper/ingest bug. Per-POI fixes are not viable. Escalate to Dataplor's DQ team with the finding as evidence.
- **DELIVERY_NOTE** — the finding is real but not actionable at delivery time. Note it in the delivery narrative; let the customer decide whether it affects their analysis.
- **IGNORE** — false positive; nothing to do.

## Apply, then decide re-export

FIXABLE_NOW findings become CSV rows for `presales_tools/bulk_observations/manual/mass_observations.py`:

```
place_id,value,path,confidence,observation_type
459743250,open,/open_status,0.95,ManualObservation
459743250,false,/opening_soon,0.95,ManualObservation
459743250,false,/temporarily_closed,0.95,ManualObservation
```

Confidence is hard-capped at 0.95 (`presales_tools`' own rule). Use `LongLivedManualObservation` for permanent-ish facts (name, category, permanently_closed) and `ManualObservation` for volatile ones (open status, hours).

After the observations land and the `place_tree_updater` PTU jobs drain, the DB (`places` + replicas) reflects the fix. But the DELIVERED CSV — the one at `s3://dataplor-data/post_export/samples/criteria_X/sample_Y/Y_final.csv` — is frozen at the moment its export ran. If the customer already downloaded it, they still have the pre-fix state.

### Re-export decision

The LLM makes the call per fix batch:

- **YES re-export** when the fix changes a column the customer will read (open_closed_status, chain_id, category, name, address, coordinates, visitation), OR the fix removes rows the client would flag as garbage, OR the fix count is > 0.01% of the sample.
- **NO re-export** when the fix affects only internal DB columns the export doesn't emit, OR the fix is on a column the post-export re-derives from other fields (in which case a re-run of `run-pipeline` against the SAME export is enough — no fresh export_job).

## Delivery gate

Never deliver a sample while the canonical-check has an unresolved CRITICAL from a FIXABLE_NOW finding on the delivered CSV. If a critical is resolved in the DB but not yet reflected in the customer's CSV, either (a) trigger a fresh export + post-export, or (b) hold the delivery until the next scheduled export cycle would pick up the fix.

## Empirical on sample 9990 (Red Bull PH, 2026-09-14)

Canonical check surfaced 1 CRITICAL + 4 WARNINGS:

| Finding | Triage | Action |
|---------|--------|--------|
| CRITICAL: 3 POIs `opening soon` + `opened_on ≤ today` | FIXABLE_NOW | wrote /open_status='open' + /opening_soon=false + /temporarily_closed=false per POI, PTU task 295894 succeeded, DB now shows status='open' |
| WARNING: ~4K rows with close time 00:00-03:59 (encoding bug) | SYSTEMIC | escalate to DQ; not fixable per-POI |
| WARNING: 2,471 POIs with pre-`opened_on` popularity entries | SYSTEMIC | escalate to DQ; needs source-side null-out |
| WARNING: 340 POIs with pre-`opened_on` sentiment entries | SYSTEMIC | escalate to DQ |
| WARNING: 25 spend outliers > 4,490 PHP | DELIVERY_NOTE | flag to client, not per-POI actionable |

Re-export decision: YES — the CRITICAL fix changes `open_closed_status`, a customer-visible column, on 3 POIs the client would have seen mislabeled. The 16 numeric-name-as-address deletes I did earlier also warrant re-export for the same reason.
