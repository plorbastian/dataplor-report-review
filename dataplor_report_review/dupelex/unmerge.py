"""Phase 5 — reverse specific merges from Phase 4 via `matches:process --split`.

The rest of the dupelex pipeline is forward-only. `unmerge.py` is the
exit door: given a list of POI ids to reverse (usually produced by
`post_audit.audit_merges`) plus the original pair set that was pushed
in Phase 4, it emits a CSV of split pairs and hands it to
`matches:process` with `action="different", state="same"`. The same
rake task drives both merges and splits on prod; the two actions
route to `PlaceMergeProcessorService(should_merge:true|false)`
internally.

Two important properties of `matches:process --split`:

  A. **The split pair must match an edge that Phase 4 actually
     pushed.** Pushing `(child_id, current_parent_id)` where the
     child was pulled in transitively (i.e. via another merge) is a
     no-op. Callers should always feed us the original pair list
     from Phase 4 and let this module pick the edges that touch the
     reversal targets.

  B. **The split is idempotent when the pair is already un-merged.**
     A pair whose two POIs have `parent_id IS NULL` re-runs
     without effect. That means callers can safely re-run the same
     unmerge CSV until every target is fully detached.

There is no observation path for `parent_id`. Do NOT try to push
`{"p": "/parent_id", "v": null}` — the admin API does not accept
place-level observations that touch merge state. The rake path here
is the only supported route.
"""
from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path
from typing import Iterable


def edges_touching(
    pushed_pairs: Iterable[tuple[int, int]],
    reversal_pids: Iterable[int],
) -> list[tuple[int, int]]:
    """Select the subset of the originally-pushed pair list where
    at least one endpoint is in `reversal_pids`. These are the pairs
    we hand to `matches:process --split`.
    """
    targets = set(reversal_pids)
    return [(a, b) for a, b in pushed_pairs if a in targets or b in targets]


def write_unmerge_csv(
    pairs: Iterable[tuple[int, int]],
    out_path: str | Path,
    default_score: float = 1.0,
) -> Path:
    """Write the CSV that `process_matches.py --split` expects."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["id_a", "id_b", "score"])
        for a, b in pairs:
            w.writerow([int(a), int(b), default_score])
    return out_path


def push_unmerge(
    csv_path: str | Path,
    admin_id: int,
    presales_tools_root: str | Path,
    *,
    dry_run: bool = False,
    timeout_seconds: int = 1200,
) -> subprocess.CompletedProcess:
    """Invoke `python bulk_observations/match_processor/process_matches.py
    <csv> <admin_id> --split` under `presales_tools_root`.

    Returns the completed process so the caller can inspect stdout /
    stderr. Raises `subprocess.CalledProcessError` on non-zero exit.
    """
    presales_tools_root = Path(presales_tools_root)
    workdir = presales_tools_root / "bulk_observations" / "match_processor"
    cmd = ["python", "process_matches.py", str(csv_path), str(admin_id), "--split"]
    if dry_run:
        cmd.append("--dry-run")
    env = os.environ.copy()
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return subprocess.run(
        cmd,
        cwd=workdir,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_seconds,
        check=True,
    )


def unmerge(
    pushed_pairs: Iterable[tuple[int, int]],
    reversal_pids: Iterable[int],
    csv_path: str | Path,
    admin_id: int,
    presales_tools_root: str | Path,
    *,
    dry_run: bool = False,
) -> tuple[Path, subprocess.CompletedProcess]:
    """End-to-end wrapper: pick edges from `pushed_pairs` that touch
    `reversal_pids`, write the CSV, and run `matches:process --split`.

    Returns the CSV path and the completed subprocess run.
    """
    edges = edges_touching(pushed_pairs, reversal_pids)
    written = write_unmerge_csv(edges, csv_path)
    proc = push_unmerge(
        written, admin_id, presales_tools_root, dry_run=dry_run,
    )
    return written, proc
