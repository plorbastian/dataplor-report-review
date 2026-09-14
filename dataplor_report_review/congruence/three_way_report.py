"""Consolidated DB ↔ export ↔ post-export diff report.

Ties `db_vs_export.compare` and `export_vs_postexport.compare` together
and returns a single dict + narrative summary suitable for a delivery
sanity-check note.

Any of the following should trigger an operator review:

  - db_vs_export.in_sp_not_in_csv > 0        (sample POI missing from export)
  - db_vs_export.leaked_children_in_csv > 0  (a merged child got delivered)
  - export_vs_postexport.added_by_pipeline > 0  (pipeline invented rows)
  - visits_stripped_by_pipeline[col] > <threshold>  (mass strip on a column
       the customer's use case cares about — cross-reference the visits
       verdict layer)
"""
from . import db_vs_export, export_vs_postexport


def build(read_conn, prod_conn, sample_id, export_csv_gz, final_csv_path,
          visit_columns=None):
    part1 = db_vs_export.compare(read_conn, prod_conn, sample_id, export_csv_gz)
    part2 = export_vs_postexport.compare(export_csv_gz, final_csv_path,
                                         visit_columns=visit_columns)

    findings = []
    if part1["in_sp_not_in_csv"] > 0:
        findings.append(f"{part1['in_sp_not_in_csv']} POIs are in sample_places but missing from the export CSV")
    if part1["leaked_children_in_csv"] > 0:
        findings.append(f"{part1['leaked_children_in_csv']} merged children leaked into the export CSV")
    if part2["added_by_pipeline"] > 0:
        findings.append(f"{part2['added_by_pipeline']} POIs appear in the final that were not in the raw export")
    for col, delta in part2["visits_stripped_by_pipeline"].items():
        if delta > 0:
            findings.append(f"pipeline stripped {delta:,} values from '{col}'")

    return {
        "sample_id": sample_id,
        "db_vs_export": part1,
        "export_vs_postexport": part2,
        "findings": findings,
        "ok": len(findings) == 0,
    }
