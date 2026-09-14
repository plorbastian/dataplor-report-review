"""Write /chain_id observations via presales_tools' mass_observations.py.

This is the canonical path for chain_id changes. Each APPLY verdict
becomes one observation row:

  {"place_id": <int>, "path": "/chain_id", "value": "<brand_slug>",
   "admin_id": <admin_id>, "source": "<source_tag>"}

After the write completes, the place_tree_updater jobs are enqueued so
`places.chain_id` propagates through the tree (parents, children,
denormalized fields).
"""
import csv
import os
import subprocess


def write_observations_csv(apply_verdicts, out_csv, admin_id=42476, source="dataplor_report_review"):
    """Write a CSV in the format mass_observations.py expects:
        place_id,path,value,admin_id,source
    """
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["place_id", "path", "value", "admin_id", "source"])
        for v in apply_verdicts:
            w.writerow([v["place_id"], "/chain_id", v["chain_id"], admin_id, source])
    return out_csv


def run_mass_observations(csv_path, presales_tools_path, queue="place_tree_updater"):
    """Shell out to presales_tools/bulk_observations/mass_observations.py.

    The script uploads to S3 and fires the observations:apply rake task,
    then enqueues PTU jobs on the given queue.
    """
    script = os.path.join(
        presales_tools_path, "bulk_observations", "mass_observations.py",
    )
    if not os.path.isfile(script):
        raise FileNotFoundError(f"mass_observations.py not found at {script}")
    return subprocess.run(
        ["python", script, csv_path, "--queue", queue],
        cwd=presales_tools_path, check=False,
    )
