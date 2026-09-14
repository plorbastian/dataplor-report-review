"""End-to-end example: chain review for sample_id=9990 (Red Bull PH).

This mirrors the 2026-09-14 run: 292 chain_id observations landed
(266 Fase A + 26 Fase B), all verified in prod + places_read.

Adjust the paths / DB config for your environment.
"""
import os
import psycopg2

from dataplor_report_review.chain import filter as ph1, enrich, llm_review, apply, verify


REPORT_GZ = "chain_report_9990.json.gz"
SCRATCH = "./scratch"
os.makedirs(SCRATCH, exist_ok=True)
OBS_CSV = os.path.join(SCRATCH, "chain_apply_9990.csv")


def get_read_conn():
    return psycopg2.connect(
        host=os.environ["DB_READ_HOST"],
        dbname=os.environ["DB_READ_NAME"],
        user=os.environ["DB_READ_USER"],
        password=os.environ["DB_READ_PASSWORD"],
    )


def get_prod_conn():
    return psycopg2.connect(
        host=os.environ["DB_PROD_HOST"],
        dbname=os.environ["DB_PROD_NAME"],
        user=os.environ["DB_PROD_USER"],
        password=os.environ["DB_PROD_PASSWORD"],
    )


# ---- Phase 1: load + filter to actionable candidates ----
report = ph1.load_chain_report(REPORT_GZ)
candidates = list(ph1.actionable_unchained(report, min_score=0.5))
print(f"actionable rank-1 candidates: {len(candidates)}")

# ---- Phase 2: enrich ----
read = get_read_conn()
place_ids = [pid for pid, _ in candidates]
chain_ids = [c.get("chain_id") for _, c in candidates]
places = enrich.pull_places(read, place_ids)
brands = enrich.pull_brands(read, set(chain_ids))

# ---- Phase 3: LLM POI-por-POI ----
#   verdict_fn takes (place_ctx, brand_ctx, candidate) and returns
#   ("APPLY" | "SKIP" | "UNCLEAR", reason). Wire to your LLM client.
def your_llm_verdict(place_ctx, brand_ctx, candidate):
    raise NotImplementedError

verdicts = llm_review.batch_verdict(candidates, places, brands, your_llm_verdict)
to_apply = llm_review.apply_list(verdicts)
print(f"APPLY: {len(to_apply)}")

# ---- Phase 4 + 5: write observations + trigger PTU ----
apply.write_observations_csv(to_apply, OBS_CSV, admin_id=42476)
# apply.run_mass_observations(OBS_CSV, presales_tools_path=r"C:\Users\sebas\Code\presales_tools")

# ---- Phase 6: verify in both roles ----
prod = get_prod_conn()
result = verify.full_check(prod, read, sample_id=9990, apply_verdicts=to_apply)
print(result)
