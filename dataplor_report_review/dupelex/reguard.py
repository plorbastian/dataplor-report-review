"""Phase 2c — refined re-guard.

The Chase-ATM guard is aggressive by design: any different `gpid` fails the pair.
But Google frequently indexes the *same* POI under two `gpid`s (e.g. after a
listing merge, or when a store is on both a mall-level and a street-level
Google Place). We recover those without weakening the guard by overriding it
only when the name+supporting-signal combination is strong.

Override rules on the `reject_guard` bucket:
  A. exact_name (name_sim >= 0.99) + any supporting signal
     → promote to auto_accept
  B. name_sim >= 0.9 + any supporting signal
     → promote to high_conf
  C. same URL host + coords < 20m
     → promote to high_conf
  D. name_sim >= 0.7 + at least 2 strong signals
     → promote to medium (defer to LLM)
"""
from .guard import chase_atm_guard  # unused re-export; kept for import parity


def norm_url_host(website):
    if not website:
        return ""
    w = website.lower().strip()
    for pref in ("http://", "https://", "www."):
        w = w.replace(pref, "")
    return w.split("/", 1)[0]


def reguard(reject_guard_bucket):
    """Reprocess the reject_guard bucket. Returns 4 lists:
    (still_reject, promoted_to_auto, promoted_to_high, promoted_to_medium).
    """
    auto, high, medium, still = [], [], [], []
    for r in reject_guard_bucket:
        try:
            name_sim = float(r.get("name_similarity") or 0)
        except (TypeError, ValueError):
            name_sim = 0
        try:
            hav = float(r.get("haversine_m") or 99999)
        except (TypeError, ValueError):
            hav = 99999
        exact_phone = str(r.get("exact_phone", "")).lower() in ("true", "1", "t")
        exact_website = str(r.get("exact_website", "")).lower() in ("true", "1", "t")
        loc_link = str(r.get("loc_parent_link", "")).lower() in ("true", "1", "t")
        close_coords = hav < 50 if hav < 99999 else False
        strong_signals = sum([exact_phone, exact_website, loc_link, close_coords])

        h1 = norm_url_host(r.get("p1_web") or r.get("place1_website") or "")
        h2 = norm_url_host(r.get("p2_web") or r.get("place2_website") or "")
        same_host = bool(h1) and h1 == h2

        exact_name = name_sim >= 0.99

        if exact_name and (close_coords or exact_phone or exact_website or loc_link):
            r["_reason"] = "override guard: exact_name + supporting"
            auto.append(r)
        elif name_sim >= 0.9 and (close_coords or exact_phone or exact_website):
            r["_reason"] = f"override guard: name_sim={name_sim:.2f} + supporting"
            high.append(r)
        elif same_host and close_coords and hav < 20:
            r["_reason"] = f"override guard: same host + very close coords ({hav:.0f}m)"
            high.append(r)
        elif name_sim >= 0.7 and strong_signals >= 2:
            r["_reason"] = f"override guard: name_sim={name_sim:.2f} + 2 strong signals"
            medium.append(r)
        else:
            still.append(r)
    return still, auto, high, medium
