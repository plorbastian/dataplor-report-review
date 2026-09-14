"""Delivered place_export CSV vs the post-export final artifact.

The post-export pipeline (sample-forge `run-pipeline`) reads the raw
place_export CSV, then runs DQ → clip (containment against the sample
boundary) → trim → rewrite → assemble → deliver. The final artifact is
`{sid}_final.csv` under `post_export/samples/criteria_{cid}/sample_{sid}/`.

Between the two we expect:
  - some POIs dropped by containment (outside the boundary)
  - some visits nullified by DQ (visitation_enabled=false)
  - some columns rewritten/renamed

We should never see:
  - MORE rows in the final than in the export (pipeline can only drop)
  - a UUID in the final that wasn't in the export (rewrite doesn't add)
  - unexpected zeroing of column families the customer's spec requires
"""
import csv
import gzip


def load_uuids(csv_path, uuid_col="dataplor_id"):
    csv.field_size_limit(50 * 1024 * 1024)
    open_fn = gzip.open if csv_path.endswith(".gz") else open
    with open_fn(csv_path, "rt", encoding="utf-8") as f:
        return {row[uuid_col] for row in csv.DictReader(f) if row.get(uuid_col)}


def load_column_coverage(csv_path, columns_of_interest):
    """Return dict[col -> non-empty count] for the requested columns."""
    csv.field_size_limit(50 * 1024 * 1024)
    open_fn = gzip.open if csv_path.endswith(".gz") else open
    out = {c: 0 for c in columns_of_interest}
    total = 0
    with open_fn(csv_path, "rt", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            total += 1
            for col in columns_of_interest:
                v = row.get(col)
                if v is not None and str(v).strip():
                    out[col] += 1
    return total, out


def compare(export_csv_path, final_csv_path, visit_columns=None,
            uuid_col="dataplor_id"):
    """Compare the raw export and the post-export final artifact."""
    exp_uuids = load_uuids(export_csv_path, uuid_col)
    fin_uuids = load_uuids(final_csv_path, uuid_col)

    visit_columns = visit_columns or [
        "estimated_visits_monthly", "estimated_visits_weekly",
        "estimated_visits_daily", "raw_visitors_monthly", "raw_visits_daily",
    ]
    exp_total, exp_cov = load_column_coverage(export_csv_path, visit_columns)
    fin_total, fin_cov = load_column_coverage(final_csv_path, visit_columns)

    return {
        "export_rows": exp_total,
        "final_rows": fin_total,
        "dropped_by_pipeline": len(exp_uuids - fin_uuids),
        "added_by_pipeline": len(fin_uuids - exp_uuids),  # must be 0
        "visits_coverage_export": exp_cov,
        "visits_coverage_final": fin_cov,
        "visits_stripped_by_pipeline": {
            c: exp_cov.get(c, 0) - fin_cov.get(c, 0) for c in visit_columns
        },
    }
