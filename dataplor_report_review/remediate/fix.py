"""Apply FIXABLE_NOW verdicts via the presales_tools mass_observations pipeline.

For each fixable finding, the LLM must produce a list of
(place_id, path, value, confidence, observation_type) tuples. This module
writes them as a CSV and calls presales_tools/bulk_observations/manual/
mass_observations.py, which:

  1. Bulk-inserts into the observations table.
  2. Enqueues Sidekiq place_tree_updater jobs on the given queue,
     which propagate the value to `places.*` and downstream views.

The confidence value is hard-capped at 0.95 per presales_tools' own rule.
Use `ManualObservation` for volatile facts (open status, hours), or
`LongLivedManualObservation` for permanent-ish facts (name, category,
permanently_closed) that shouldn't decay.
"""
import csv
import os
import subprocess


CONFIDENCE_CAP = 0.95


def write_observations_csv(rows, out_csv):
    """Write observation rows in the format mass_observations.py expects.

    Each row: dict with keys place_id, value, path, confidence (<= 0.95),
    observation_type.
    """
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["place_id", "value", "path", "confidence", "observation_type"])
        for r in rows:
            conf = min(float(r.get("confidence", CONFIDENCE_CAP)), CONFIDENCE_CAP)
            w.writerow([r["place_id"], r["value"], r["path"], conf,
                        r.get("observation_type", "ManualObservation")])
    return out_csv


def run_mass_observations(csv_path, presales_tools_path, admin_id=42476,
                          queue="place_tree_updater"):
    """Shell out to mass_observations.py to apply the observations."""
    script = os.path.join(
        presales_tools_path, "bulk_observations", "manual", "mass_observations.py",
    )
    if not os.path.isfile(script):
        raise FileNotFoundError(f"mass_observations.py not found at {script}")
    cmd = [
        "python", script,
        "--file_path", csv_path,
        "--admin_id", str(admin_id),
        "--updater_queue", queue,
    ]
    return subprocess.run(cmd, cwd=presales_tools_path, check=False)


# ---------- Common finding-to-observation templates ----------

def open_closed_status_open(place_ids, value="open"):
    """For POIs where the canonical check flagged an opening_soon
    contradiction, write /open_status = 'open' plus clear the boolean
    flags that make the export re-derive 'opening soon'.

    Returns a list of observation rows ready for `write_observations_csv`.
    """
    rows = []
    for pid in place_ids:
        rows.append({"place_id": pid, "value": value, "path": "/open_status",
                    "confidence": CONFIDENCE_CAP, "observation_type": "ManualObservation"})
        rows.append({"place_id": pid, "value": "false", "path": "/opening_soon",
                    "confidence": CONFIDENCE_CAP, "observation_type": "ManualObservation"})
        rows.append({"place_id": pid, "value": "false", "path": "/temporarily_closed",
                    "confidence": CONFIDENCE_CAP, "observation_type": "ManualObservation"})
    return rows


def permanently_closed(place_ids, value=True):
    """For confirmed-closed POIs, write /permanently_closed = true."""
    return [{"place_id": pid, "value": str(value).lower(),
             "path": "/permanently_closed",
             "confidence": CONFIDENCE_CAP,
             "observation_type": "LongLivedManualObservation"} for pid in place_ids]
