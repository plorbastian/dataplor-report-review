"""Phase 3.5a — safety filter over the consolidated merge list.

Even after guards and LLM review, the merge list can contain drift-prone
pairs. This filter is a set of *rejection* patterns, never approval
patterns. Each pattern captures a specific failure mode we've hit:

  A. container + tenant with different names
     e.g. "Power Plant Mall" <-> "Zara" — the mall row and a tenant row
     should never merge. Any pair where one place is a container-like
     category (shopping_center, medical_center, hospital, corporate_office,
     tower, building, university, transit_station, ...) and the other is
     not a container AND names differ is rejected.

  B. practitioners with different names
     e.g. "Dr. Anna Sta. Maria @ Makati Med" <-> "Dr. Maria Domingo @
     Makati Med". Two people are not one POI regardless of shared address.

  C. distinct brand prefixes
     e.g. "Zara" <-> "Sbarro" at the same mall via a shared parent. If
     name_similarity is low AND both first-tokens are non-generic brand
     names, the pair is rejected.

  D. hospital departments
     e.g. "Office of the Surgery - Makati Medical Center" <-> "Hematology
     Office - Makati Medical Center". Both mention the hospital by name
     but the department part differs, so they are distinct offices.
"""
import re

CONTAINER_CATEGORIES = {
    "shopping_center", "shopping_mall", "medical_center", "private_hospital",
    "hospital", "corporate_office", "building", "commercial_building", "tower",
    "office_building", "condominium_complex", "condominium", "university",
    "college", "school", "government_office", "transit_station",
    "train_station", "airport",
}

PRACTITIONER_CATEGORIES = {
    "general_practitioner", "lawyer", "dentist", "psychiatrist", "pulmonologist",
    "orthodontist", "chiropractor", "physiotherapist", "cardiologist",
    "dermatologist", "gynecologist", "pediatrician", "ophthalmologist",
    "optometrist", "psychologist", "notary_public", "radiologist", "surgeon",
    "urologist", "oncologist", "neurologist", "endocrinologist",
}

DEPARTMENT_KEYWORDS = ("office of the", "section", "department", "clinic", "ward")

GENERIC_PREFIX_TOKENS = {
    "the", "new", "old", "a", "an", "poi", "mall", "office", "room", "floor",
    "ph", "philippines", "makati", "manila",
}


def practitioner_name_key(name):
    """Return a lowercased key identifying the practitioner in a name, or None."""
    if not name:
        return None
    n = name.lower()
    for prefix in ("dr. ", "atty. ", "dra. ", "attorney ", "dr ", "atty "):
        if n.startswith(prefix):
            return n[len(prefix):].split(",")[0].split("@")[0].strip()[:40]
    m = re.search(r"^(.*?)\s*(?:,|\s@|\s-)\s*", name)
    if m and ("MD" in name or "M.D." in name or "DMD" in name):
        return m.group(1).lower().strip()[:40]
    return None


def brand_prefix(name):
    if not name:
        return ""
    n = name.lower().strip()
    for prefix in ("dr. ", "atty. ", "dra. ", "the "):
        if n.startswith(prefix):
            n = n[len(prefix):]
    return n.split()[0][:20] if n else ""


def is_container(cat, name):
    if cat in CONTAINER_CATEGORIES:
        return True
    if name and any(k in name.lower() for k in DEPARTMENT_KEYWORDS):
        return True
    return False


def _name_sim(pair):
    try:
        return float(pair.get("name_similarity") or 0)
    except (TypeError, ValueError):
        return 0


def safety_reject(pair):
    """Return (rejected: bool, reason: str). A pair that fails ANY of the
    rejection patterns is rejected."""
    n1, n2 = pair.get("p1_name") or "", pair.get("p2_name") or ""
    c1, c2 = pair.get("p1_cat") or "", pair.get("p2_cat") or ""
    n1l, n2l = n1.lower().strip(), n2.lower().strip()

    cont1, cont2 = is_container(c1, n1), is_container(c2, n2)
    if cont1 != cont2 and n1l != n2l:
        return True, f"container+tenant mismatch ({c1}='{n1[:30]}' vs {c2}='{n2[:30]}')"

    k1, k2 = practitioner_name_key(n1), practitioner_name_key(n2)
    if k1 and k2 and k1 != k2:
        return True, f"different practitioners ({k1} vs {k2})"
    if c1 in PRACTITIONER_CATEGORIES and c2 in PRACTITIONER_CATEGORIES and n1l != n2l:
        return True, f"different practitioners ({c1}: {n1[:25]} vs {n2[:25]})"

    if _name_sim(pair) < 0.5:
        b1, b2 = brand_prefix(n1), brand_prefix(n2)
        if b1 and b2 and b1 != b2 and b1 not in GENERIC_PREFIX_TOKENS \
           and b2 not in GENERIC_PREFIX_TOKENS and len(b1) >= 3 and len(b2) >= 3:
            if not (b1.startswith(b2) or b2.startswith(b1)):
                return True, f"distinct brand prefixes ({b1} vs {b2})"

    if "makati medical center" in n1l and "makati medical center" in n2l:
        if (any(k in n1l for k in DEPARTMENT_KEYWORDS)
                or any(k in n2l for k in DEPARTMENT_KEYWORDS)):
            if n1l != n2l:
                return True, "different Makati Med departments"

    return False, ""


def apply_safety_filter(merge_pairs, allowlist=None):
    """Split `merge_pairs` into (kept, rejected). `allowlist` is an optional
    set of frozenset({id1, id2}) pairs that bypass the filter (e.g.
    hand-approved LLM verdicts you don't want the safety filter to override).
    """
    allowlist = allowlist or set()
    kept, rejected = [], []
    for p in merge_pairs:
        key = frozenset({int(p["place1_id"]), int(p["place2_id"])})
        if key in allowlist:
            kept.append(p)
            continue
        bad, reason = safety_reject(p)
        if bad:
            p["_reject_reason"] = reason
            rejected.append(p)
        else:
            kept.append(p)
    return kept, rejected
