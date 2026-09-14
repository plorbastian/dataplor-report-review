"""Phase 3.5b — strict-name filter over big components.

Union-find over the surviving merge pairs. If a pair sits in a component
of size >= N (default 3), we require both places' normalized names to be
literally identical, otherwise we drop the pair. This is a specific defense
against transitive drift:

  Pair (A, B) legit — same name.
  Pair (B, C) legit — same name.
  Pair (C, D) legit — same name.
  ...but the four end up merged into one component. If A/B/C/D really are
  the same POI, they'll all normalize to the same string. If any of them
  disagrees, the drift chain is broken.

Also supports an `allowlist` set of pair-keys that bypass the strict rule
(useful for hand-approved LLM verdicts where the names legitimately differ).
"""
import re


def _norm(s):
    if not s:
        return ""
    s = s.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)
    return " ".join(s.split())


def build_components(pairs):
    parent = {}

    def find(x):
        while parent.get(x, x) != x:
            parent[x] = parent.get(parent[x], parent[x])
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for p in pairs:
        a = int(p["place1_id"])
        b = int(p["place2_id"])
        parent.setdefault(a, a)
        parent.setdefault(b, b)
        union(a, b)

    comps = {}
    for pid in parent:
        r = find(pid)
        comps.setdefault(r, []).append(pid)

    return parent, comps, find


def apply_strict_name_filter(pairs, min_component_size=3, allowlist=None):
    """Drop pairs whose connected-component size >= min_component_size
    AND whose normalized names disagree. `allowlist` is a set of
    frozenset({id1, id2}) pairs that always survive."""
    allowlist = allowlist or set()
    _, comps, find = build_components(pairs)
    csize = {root: len(members) for root, members in comps.items()}

    kept, dropped = [], []
    for p in pairs:
        key = frozenset({int(p["place1_id"]), int(p["place2_id"])})
        if key in allowlist:
            kept.append(p)
            continue
        sz = csize[find(int(p["place1_id"]))]
        if sz >= min_component_size:
            n1, n2 = _norm(p.get("p1_name")), _norm(p.get("p2_name"))
            if n1 and n1 == n2:
                kept.append(p)
            else:
                p["_drop_reason"] = f"size={sz} component with non-identical names"
                dropped.append(p)
        else:
            kept.append(p)
    return kept, dropped


def component_size_histogram(pairs):
    _, comps, _ = build_components(pairs)
    sizes = {}
    for members in comps.values():
        sz = len(members)
        sizes[sz] = sizes.get(sz, 0) + 1
    return sizes, len(comps)
