"""Phase 3.6 — post-merge audit over the merges that landed on prod.

The pipeline is forward-only up through Phase 4 (`merge_push`): once
matches:process succeeds, we assume the merges are correct. That
assumption breaks in three specific ways we have hit in the field, all
of which slip past guard + safety + strict:

  1. **Transitive drift** — A↔B and B↔C were both merged pairwise,
     but the {A, B, C} connected component contains a POI whose
     outward postcode (UK) or ADM2 (US) does not match the rest of
     the cluster. The single-pair guard is blind to component-level
     structure. First hit on GB coffee (2026-09-18/21): the strict
     manual filter for costa_coffee let 17 cross-postcode POIs get
     transitively pulled into UK-national clusters via a shared
     spurious coordinate.

  2. **Cross-brand within component** — a component contains POIs
     with different `chain_id` values. Guard and safety only look at
     the current pair, so a chain across `starbucks` ↔ NULL-chain ↔
     `costa_coffee` (via two consecutive pairs) can collapse two
     brands into one parent. First hit on GB coffee (2026-09-21):
     16 components with `starbucks + blankstreet`, one with
     `starbucks + caffe_nero`.

  3. **Verified-into-provisional flip** — a `provisional=false`
     child ends up under a `provisional=true` parent because
     `MatchProcessorService` picks parent by data richness and the
     provisional record often has more scraped data. Whether this
     is bad depends on the brand and the delivery — some workflows
     want the verified to win regardless. Flagged, not auto-actioned.

The output of this module is a list of POI ids to reverse and the
failure mode that flagged each one, ready to feed into `unmerge.py`.
This never rewrites `parent_id` itself; it only produces the
reversal candidate list.

The check-in-line-then-verdict shape mirrors the rest of the
dupelex modules. The three detectors run independently and their
outputs are merged in `audit_merges`.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Iterable, Optional


@dataclass
class ReversalCandidate:
    """One POI id flagged for `matches:process --split`."""

    place_id: int
    failure_modes: list[str] = field(default_factory=list)

    def add_reason(self, reason: str) -> None:
        self.failure_modes.append(reason)


def _connected_components(
    pairs: Iterable[tuple[int, int]],
) -> list[set[int]]:
    """Undirected connected components from (id_a, id_b) pairs."""
    adj: dict[int, set[int]] = defaultdict(set)
    for a, b in pairs:
        adj[a].add(b)
        adj[b].add(a)
    seen: set[int] = set()
    comps: list[set[int]] = []
    for start in adj:
        if start in seen:
            continue
        comp: set[int] = set()
        stack = [start]
        while stack:
            node = stack.pop()
            if node in seen:
                continue
            seen.add(node)
            comp.add(node)
            stack.extend(adj[node] - seen)
        comps.append(comp)
    return comps


def _outward_uk(postcode: str) -> str:
    """UK outward postcode (part before the space, or first 4 chars)."""
    if not postcode:
        return ""
    postcode = postcode.upper().strip()
    if " " in postcode:
        return postcode.split()[0]
    return postcode[:4] if len(postcode) >= 4 else postcode


def detect_transitive_drift(
    components: list[set[int]],
    place_meta: dict[int, dict],
    country: str = "gb",
    min_component: int = 3,
) -> dict[int, str]:
    """POIs whose sub-region key does not match the biggest sub-region
    in their component. For UK we use outward postcode; for other
    countries the caller may pass an `adm2`/`state` key on the meta
    dict and select via `country`.

    Returns {place_id: reason_str} for every flagged POI.
    """
    key_fn = _outward_uk if country.lower() == "gb" else (lambda pc: pc)
    flagged: dict[int, str] = {}
    for comp in components:
        if len(comp) < min_component:
            continue
        buckets: dict[str, list[int]] = defaultdict(list)
        for pid in comp:
            m = place_meta.get(pid) or {}
            k = key_fn(m.get("postcode") or m.get("adm2") or "")
            if k:
                buckets[k].append(pid)
        if len(buckets) < 2:
            continue
        # Keep the biggest bucket. Every POI in the smaller buckets is
        # a candidate for reversal.
        sorted_buckets = sorted(buckets.items(), key=lambda kv: -len(kv[1]))
        keep_key = sorted_buckets[0][0]
        for other_key, ids in sorted_buckets[1:]:
            for pid in ids:
                flagged[pid] = (
                    f"TRANSITIVE_DRIFT: sub-region '{other_key}' in a "
                    f"component of size {len(comp)} dominated by '{keep_key}'"
                )
    return flagged


def detect_cross_brand(
    components: list[set[int]],
    place_meta: dict[int, dict],
) -> dict[int, str]:
    """POIs whose `chain_id` differs from the dominant chain in the
    component. NULL-chain POIs are ignored here — they can be
    legitimate additions absorbed into a chain component.

    Returns {place_id: reason_str}.
    """
    flagged: dict[int, str] = {}
    for comp in components:
        chains: dict[str, list[int]] = defaultdict(list)
        for pid in comp:
            ch = (place_meta.get(pid) or {}).get("chain_id") or ""
            if ch:
                chains[ch].append(pid)
        if len(chains) < 2:
            continue
        sorted_chains = sorted(chains.items(), key=lambda kv: -len(kv[1]))
        keep_chain = sorted_chains[0][0]
        for other_chain, ids in sorted_chains[1:]:
            for pid in ids:
                flagged[pid] = (
                    f"CROSS_BRAND: chain_id '{other_chain}' in a "
                    f"component dominated by chain_id '{keep_chain}'"
                )
    return flagged


def detect_provisional_flip(
    pairs: Iterable[tuple[int, int]],
    place_meta: dict[int, dict],
) -> dict[int, str]:
    """Reports where a `provisional=False` POI is a direct child of a
    `provisional=True` parent (via `parent_id`). This is informational
    on most workflows — see the docstring at the top of the module —
    so the caller decides whether to act on it.
    """
    flagged: dict[int, str] = {}
    for pid, meta in place_meta.items():
        parent_id = meta.get("parent_id")
        if parent_id is None:
            continue
        parent = place_meta.get(parent_id)
        if not parent:
            continue
        if meta.get("provisional") is False and parent.get("provisional") is True:
            flagged[pid] = (
                f"PROVISIONAL_FLIP: verified child under provisional "
                f"parent {parent_id}. May be intentional under the "
                f"dupelex 200m-radius universe scope."
            )
    return flagged


def audit_merges(
    pairs: Iterable[tuple[int, int]],
    place_meta: dict[int, dict],
    country: str = "gb",
    include_provisional_flip: bool = False,
) -> list[ReversalCandidate]:
    """Run all three detectors and consolidate their output.

    Args:
      pairs: the (id_a, id_b) pairs that were pushed via
        `matches:process` (Phase 4 merge_push output).
      place_meta: {place_id: {postcode, chain_id, provisional,
        parent_id, ...}}. Callers usually populate this from
        `dupelex.enrich`.
      country: which sub-region rule to apply. "gb" uses UK outward
        postcode; other codes fall back to the raw `adm2` field.
      include_provisional_flip: whether to include the
        verified-into-provisional detector. Off by default because
        the pattern is often intentional under dupelex's 200m-radius
        universe scope.

    Returns a list of :class:`ReversalCandidate`. A POI id can carry
    multiple failure modes if it matched more than one detector.
    """
    pair_list = list(pairs)
    comps = _connected_components(pair_list)

    by_pid: dict[int, ReversalCandidate] = {}

    for pid, reason in detect_transitive_drift(comps, place_meta, country).items():
        by_pid.setdefault(pid, ReversalCandidate(place_id=pid)).add_reason(reason)
    for pid, reason in detect_cross_brand(comps, place_meta).items():
        by_pid.setdefault(pid, ReversalCandidate(place_id=pid)).add_reason(reason)
    if include_provisional_flip:
        for pid, reason in detect_provisional_flip(pair_list, place_meta).items():
            by_pid.setdefault(pid, ReversalCandidate(place_id=pid)).add_reason(reason)

    return list(by_pid.values())
