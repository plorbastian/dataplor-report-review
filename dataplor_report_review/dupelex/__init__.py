"""dupelex sub-package — see docs/dupelex/methodology.md for the full write-up."""
from . import (
    filter, enrich, guard, reguard, llm_review, safety, strict,
    merge_push, sample_cleanup, verify, post_audit, unmerge,
)

__all__ = ["filter", "enrich", "guard", "reguard", "llm_review",
           "safety", "strict", "merge_push", "sample_cleanup", "verify",
           "post_audit", "unmerge"]
