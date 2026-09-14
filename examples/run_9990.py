"""End-to-end example: process the dupelex report for sample_id=9990.

This mirrors the 2026-09-14 run against the Red Bull PH sample:
  - Input: dupelex_9990_514683.csv.gz (29.5M pairs, 5.9 GB raw)
  - Output: 1,516 confirmed merges via matches:process on Fargate

Adjust the paths and DB config for your environment before running.
"""
import os
import json
import psycopg2

from dupelex_llm_review import (
    filter as ph1,
    enrich as ph2a,
    guard as ph2b,
    reguard as ph2c,
    llm_review as ph3,
    safety as ph3_5a,
    strict as ph3_5b,
    merge_push as ph4,
)


SCRATCH = "./scratch"
os.makedirs(SCRATCH, exist_ok=True)

RAW = "dupelex_9990_514683.csv.gz"
ACTIONABLE_CSV = os.path.join(SCRATCH, "dupelex_9990_actionable.csv")
FINAL_CSV = os.path.join(SCRATCH, "dupelex_9990_merges_final.csv")


def get_read_conn():
    return psycopg2.connect(
        host=os.environ["DB_READ_HOST"],
        dbname=os.environ["DB_READ_NAME"],
        user=os.environ["DB_READ_USER"],
        password=os.environ["DB_READ_PASSWORD"],
        port=int(os.environ.get("DB_READ_PORT", 5432)),
    )


# ---- Phase 1: filter raw ----
ph1.filter_raw_dupelex(RAW, ACTIONABLE_CSV, min_score=0.5)

# ---- Phase 2a: enrich ----
pairs = ph2a.load_pairs(ACTIONABLE_CSV)
pids = ph2a.distinct_place_ids(pairs)
conn = get_read_conn()
places = ph2a.pull_places(conn, pids)

# Copy DB-derived fields onto each pair so downstream phases don't need the DB
for r in pairs:
    p1 = places.get(int(r["place1_id"])) or {}
    p2 = places.get(int(r["place2_id"])) or {}
    r["p1_name"] = p1.get("name", ""); r["p2_name"] = p2.get("name", "")
    r["p1_cat"]  = p1.get("category", ""); r["p2_cat"]  = p2.get("category", "")
    r["p1_addr"] = p1.get("address", ""); r["p2_addr"] = p2.get("address", "")
    r["p1_web"]  = p1.get("website", "");  r["p2_web"]  = p2.get("website", "")

# ---- Phase 2b: guards ----
buckets = ph2b.bucket_all(pairs, places)
print({k: len(v) for k, v in buckets.items()})

# ---- Phase 2c: refined re-guard on reject_guard ----
still_reject, back_auto, back_high, back_medium = ph2c.reguard(buckets["reject_guard"])
buckets["auto_accept"].extend(back_auto)
buckets["high_conf"].extend(back_high)
buckets["medium"].extend(back_medium)
buckets["reject_guard"] = still_reject

# ---- Phase 3: LLM medium review ----
# First, promote obvious string-exact-name dupes out of medium
still_medium, str_auto, str_high = ph3.bulk_string_exact_promotion(buckets["medium"])
buckets["auto_accept"].extend(str_auto)
buckets["high_conf"].extend(str_high)
buckets["medium"] = still_medium

# Then wire your LLM in — this is your judgment step:
#   verdicts = ph3.batch_verdict(still_medium, verdict_fn=your_llm_callback)
#   ph3.apply_verdicts(still_medium, verdicts)
# For the 9990 example the operator hand-approved 4 pairs after inline review.

# ---- Phase 3.5a: safety filter ----
merge_pairs = ph3.merge_pairs_from_tiers(buckets)
hand_approved = set()  # frozensets of hand-approved pair ids from Phase 3
kept, safety_rejects = ph3_5a.apply_safety_filter(merge_pairs, allowlist=hand_approved)

# ---- Phase 3.5b: strict-name over big components ----
final_pairs, drift_drops = ph3_5b.apply_strict_name_filter(
    kept, min_component_size=3, allowlist=hand_approved
)
print(f"final merges: {len(final_pairs)}")

# ---- Phase 4: write CSV + trigger matches:process ----
ph4.write_pair_csv(final_pairs, FINAL_CSV)
# ph4.trigger_matches_process(
#     FINAL_CSV,
#     admin_id=42476,
#     presales_tools_path=r"C:\Users\sebas\Code\presales_tools",
# )
