"""Union-find residual-dupe clustering on the delivered CSV.

The pair-based checks in `checks.same_chain_close` and
`checks.residual_name_dupes` return unordered pairs. When the same
POI is duplicated 3-5 times at the same location, that produces
many pairs that are actually one cluster. This helper collapses
those into connected components, which is the right unit for the
LLM verdict (decide "is this cluster one POI or several?" instead
of pair-by-pair).

Also, DO NOT auto-skip containers/buildings/govt/church categories —
those clusters are usually the same real venue duplicated (LKG Tower,
Perla Mansion, Ecoplaza Building all showed up as legit dupes on
sample 9990). The LLM must decide per component.
"""
import math
from collections import defaultdict


def _hav(a, b):
    lat1, lng1 = a; lat2, lng2 = b
    R = 6371000
    p1 = math.radians(lat1); p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1); dl = math.radians(lng2 - lng1)
    x = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(x))


def cluster_same_name(rows, max_meters=50, min_name_len=4, skip_group_larger_than=30):
    """Given an iterable of dicts with keys id, name, latitude, longitude,
    category (any extra keys are preserved), return a list of components.
    Each component is a list of dicts, all sharing a normalized name and
    all within `max_meters` of each other (connected — not necessarily
    a full clique). Components of size 1 are dropped.
    """
    by_name = defaultdict(list)
    for r in rows:
        n = (r.get("name") or "").strip().lower()
        try:
            lat = float(r.get("latitude") or 0)
            lng = float(r.get("longitude") or 0)
        except (TypeError, ValueError):
            continue
        if len(n) >= min_name_len and (lat or lng):
            by_name[n].append({**r, "_lat": lat, "_lng": lng})

    components = []
    for n, group in by_name.items():
        if len(group) < 2 or len(group) > skip_group_larger_than:
            continue
        parent = list(range(len(group)))

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                if _hav((group[i]["_lat"], group[i]["_lng"]),
                        (group[j]["_lat"], group[j]["_lng"])) < max_meters:
                    union(i, j)

        comps = defaultdict(list)
        for i in range(len(group)):
            comps[find(i)].append(group[i])
        for comp in comps.values():
            if len(comp) >= 2:
                components.append(comp)
    return components


def pairs_from_component(component, base_index=0):
    """Emit (id_a, id_b) pairs merging every other member into
    component[base_index]. Callers can pick a different base via
    the LLM (e.g. "the one with the richest metadata")."""
    base = component[base_index]
    return [(base["id"], other["id"])
            for i, other in enumerate(component)
            if i != base_index]
