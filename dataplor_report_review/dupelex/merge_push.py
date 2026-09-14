"""Phase 4 — push the final merge pair CSV to DataPlor's matches:process rake task.

This module wraps the DataPlor pattern:
  - Write the pair CSV in `id_a,id_b,score` format.
  - Call `bulk_observations/match_processor/process_matches.py` (in the
    presales_tools repo) which uploads the payload to S3 and POSTs
    /v3/admin/rake_tasks to fire the `matches:process` rake on Fargate.
  - Poll the container task until completion.

This module does NOT re-implement the transport; it just prepares the
CSV in the canonical format and points the caller at the entry point.
"""
import csv
import os
import subprocess


def write_pair_csv(pairs, out_csv, default_score=0.95):
    """Write pairs as `id_a,id_b,score` to `out_csv`. Each pair is a dict
    with 'place1_id' + 'place2_id' keys (optionally 'score')."""
    with open(out_csv, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["id_a", "id_b", "score"])
        for p in pairs:
            score = p.get("score", default_score)
            try:
                score = float(score)
            except (TypeError, ValueError):
                score = default_score
            w.writerow([p["place1_id"], p["place2_id"], score])
    return out_csv


def trigger_matches_process(pair_csv, admin_id, presales_tools_path,
                            dry_run=False, no_wait=False):
    """Shell out to presales_tools' process_matches.py.

    Args:
      pair_csv: path to a CSV with id_a,id_b,score columns.
      admin_id: numeric admin_id for attribution (e.g. 42476 for Sebastian).
      presales_tools_path: local checkout of the presales_tools repo.
      dry_run: if True, pass --dry-run (no S3 upload, no Fargate).
      no_wait: if True, pass --no-wait (skip polling the container task).

    Returns the CompletedProcess object.
    """
    script = os.path.join(
        presales_tools_path, "bulk_observations", "match_processor",
        "process_matches.py",
    )
    if not os.path.isfile(script):
        raise FileNotFoundError(f"process_matches.py not found at {script}")
    cmd = ["python", script, pair_csv, str(admin_id)]
    if dry_run:
        cmd.append("--dry-run")
    if no_wait:
        cmd.append("--no-wait")
    return subprocess.run(cmd, cwd=presales_tools_path, check=False)
