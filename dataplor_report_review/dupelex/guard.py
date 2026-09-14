"""Phase 2b — Chase-ATM guard + category-family guard.

Bucket each enriched pair into one of:
  auto_accept      — exact_name + at least one supporting signal AND passes both guards
  high_conf        — name_sim >= 0.9 + supporting AND passes both guards
  medium           — passes guards but signals ambiguous → hand off to Phase 3 LLM
  reject_guard     — Chase-ATM guard fails (distinguishability)
  reject_category  — category-family mismatch (bank vs restaurant)
  skip_missing     — one of the place_ids not in DB
"""

CATEGORY_FAMILIES = [
    {"bank", "atm", "credit_union", "currency_exchange", "money_transfer_service"},
    {"restaurant", "fast_food_restaurant", "cafe", "bakery", "coffee_shop",
     "chicken_restaurant", "pizza_restaurant"},
    {"clothing_store", "shoe_store", "department_store", "supermarket",
     "grocery_store", "convenience_store", "variety_store"},
    {"gas_station", "car_dealer", "car_repair", "auto_parts_store",
     "motor_vehicle_dealer", "car_wash", "tire_shop"},
    {"drugstore", "pharmacy", "hospital", "clinic", "medical_clinic"},
    {"hotel", "motel", "hostel", "private_guest_room", "lodging"},
    {"school", "university", "college", "preschool", "kindergarten",
     "language_school", "training_center"},
]


def category_family_id(cat):
    for family in CATEGORY_FAMILIES:
        if cat in family:
            return id(family)
    return None


def norm_url_slug(website):
    if not website:
        return ""
    w = website.lower().strip()
    for pref in ("http://", "https://", "www."):
        w = w.replace(pref, "")
    if "/" in w:
        return w.split("/", 1)[1].split("?")[0].strip("/")
    return ""


def chase_atm_guard(p1, p2):
    """Return (passes, reason). Fails when strong distinguishing signals differ.

    - Different `gpid` (Google Places ID) at same coordinates → distinct POIs
      that Google indexed as separate entries (the "Chase-ATM" pattern).
    - Different `url_slug` (Yext-style location path) → distinct locations.
    - Different `yext_source` → distinct Yext entries.
    """
    if p1["gpid"] and p2["gpid"] and p1["gpid"] != p2["gpid"]:
        return False, f"different gpids ({p1['gpid'][:12]}... vs {p2['gpid'][:12]}...)"
    s1, s2 = norm_url_slug(p1["website"]), norm_url_slug(p2["website"])
    if s1 and s2 and s1 != s2 and len(s1) > 3 and len(s2) > 3:
        if s1 not in s2 and s2 not in s1:
            return False, f"different url slugs ({s1[:30]} vs {s2[:30]})"
    if p1["y_source"] and p2["y_source"] and p1["y_source"] != p2["y_source"]:
        return False, "different yext sources"
    return True, ""


def bucket_pair(row, p1, p2):
    """Assign a bucket label + reason for one enriched pair."""
    if not p1 or not p2:
        return "skip_missing", "one place not in DB"
    try:
        name_sim = float(row.get("name_similarity") or 0)
    except (TypeError, ValueError):
        name_sim = 0
    try:
        haversine = float(row.get("haversine_m") or 99999)
    except (TypeError, ValueError):
        haversine = 99999
    exact_phone = str(row.get("exact_phone", "")).lower() in ("true", "1", "t")
    exact_website = str(row.get("exact_website", "")).lower() in ("true", "1", "t")
    loc_link = str(row.get("loc_parent_link", "")).lower() in ("true", "1", "t")

    exact_name = name_sim >= 0.99
    close_coords = haversine < 50
    strong_signals = sum([exact_phone, exact_website, loc_link, close_coords])

    f1 = category_family_id(p1["category"])
    f2 = category_family_id(p2["category"])
    if f1 and f2 and f1 != f2:
        return "reject_category", f"cat family mismatch {p1['category']} vs {p2['category']}"

    ok, why = chase_atm_guard(p1, p2)
    if not ok:
        return "reject_guard", f"chase-ATM guard: {why}"

    if exact_name and strong_signals >= 1:
        return "auto_accept", "exact_name + strong signal(s)"
    if name_sim >= 0.9 and strong_signals >= 1:
        return "high_conf", f"name_sim={name_sim:.2f} + strong signal(s)"
    return "medium", "needs LLM review"


def bucket_all(pairs, places):
    """Run bucketing over every pair. Returns dict[bucket_name -> list of pairs]."""
    buckets = {k: [] for k in ("auto_accept", "high_conf", "medium",
                                "reject_guard", "reject_category", "skip_missing")}
    for row in pairs:
        p1 = places.get(int(row["place1_id"]))
        p2 = places.get(int(row["place2_id"]))
        label, reason = bucket_pair(row, p1, p2)
        row["_reason"] = reason
        buckets[label].append(row)
    return buckets
