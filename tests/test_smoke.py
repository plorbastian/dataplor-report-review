"""Smoke tests — verify the seven-layer package imports and each layer
exposes its documented public surface. No DB / LLM / network calls;
run with `python -m unittest discover tests`.
"""
import unittest


class TestPackageStructure(unittest.TestCase):
    def test_top_level_imports(self):
        import dataplor_report_review
        self.assertTrue(hasattr(dataplor_report_review, "__version__"))

    def test_all_seven_layers_present(self):
        from dataplor_report_review import (
            dupelex, chain, export_qa, visits, congruence, darc_check,
            remediate,
        )
        for mod in (dupelex, chain, export_qa, visits, congruence,
                    darc_check, remediate):
            self.assertTrue(mod.__doc__, f"{mod.__name__} missing docstring")


class TestDupelex(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.dupelex import (
            filter, enrich, guard, reguard, llm_review, safety, strict,
            merge_push, sample_cleanup, verify, post_audit, unmerge,
        )
        # Guard has the category families
        self.assertGreaterEqual(len(guard.CATEGORY_FAMILIES), 5)
        # Safety exposes the rejection function
        self.assertTrue(callable(safety.safety_reject))
        # Strict has the component builder
        self.assertTrue(callable(strict.build_components))
        # Post-audit detectors are all callable
        self.assertTrue(callable(post_audit.audit_merges))
        self.assertTrue(callable(post_audit.detect_transitive_drift))
        self.assertTrue(callable(post_audit.detect_cross_brand))
        self.assertTrue(callable(post_audit.detect_provisional_flip))
        # Unmerge exposes end-to-end + granular helpers
        self.assertTrue(callable(unmerge.edges_touching))
        self.assertTrue(callable(unmerge.write_unmerge_csv))
        self.assertTrue(callable(unmerge.unmerge))


class TestDupelexPostAudit(unittest.TestCase):
    """Behavioural tests for the failure-mode detectors, using
    fixtures modelled after the 2026-09-21 GB coffee incident."""

    def test_transitive_drift_flags_only_the_outliers(self):
        from dataplor_report_review.dupelex.post_audit import (
            audit_merges, ReversalCandidate,
        )
        # Component {1,2,3,4}: three in TR14, one straggler in E1 5SD.
        pairs = [(1, 2), (2, 3), (3, 4)]
        meta = {
            1: {"postcode": "TR14 8DT"},
            2: {"postcode": "TR14 8DT"},
            3: {"postcode": "TR14 8DT"},
            4: {"postcode": "E1 5SD"},  # the outlier
        }
        out = audit_merges(pairs, meta, country="gb")
        pids = {c.place_id for c in out}
        self.assertEqual(pids, {4})
        self.assertTrue(any(
            "TRANSITIVE_DRIFT" in r for r in out[0].failure_modes
        ))

    def test_cross_brand_flags_the_smaller_chain(self):
        from dataplor_report_review.dupelex.post_audit import audit_merges
        # {10, 11} both starbucks, {12} caffe_nero, all linked.
        pairs = [(10, 11), (11, 12)]
        meta = {
            10: {"chain_id": "starbucks", "postcode": "SE1 8LL"},
            11: {"chain_id": "starbucks", "postcode": "SE1 8LL"},
            12: {"chain_id": "caffe_nero", "postcode": "SE1 8LL"},
        }
        out = audit_merges(pairs, meta, country="gb")
        pids = {c.place_id for c in out}
        self.assertEqual(pids, {12})
        self.assertTrue(any(
            "CROSS_BRAND" in r for r in out[0].failure_modes
        ))

    def test_provisional_flip_off_by_default(self):
        from dataplor_report_review.dupelex.post_audit import audit_merges
        pairs = [(20, 21)]
        meta = {
            20: {"provisional": False, "parent_id": 21,
                 "postcode": "N1 9AA", "chain_id": "starbucks"},
            21: {"provisional": True, "parent_id": None,
                 "postcode": "N1 9AA", "chain_id": "starbucks"},
        }
        # Off by default -> no findings
        self.assertEqual(audit_merges(pairs, meta), [])
        # On explicitly -> flagged
        out = audit_merges(pairs, meta, include_provisional_flip=True)
        pids = {c.place_id for c in out}
        self.assertEqual(pids, {20})

    def test_unmerge_edges_touching_selects_correctly(self):
        from dataplor_report_review.dupelex.unmerge import edges_touching
        pushed = [(1, 2), (2, 3), (3, 4), (5, 6)]
        selected = edges_touching(pushed, [4])
        self.assertEqual(selected, [(3, 4)])
        selected2 = edges_touching(pushed, [2, 6])
        self.assertEqual(selected2, [(1, 2), (2, 3), (5, 6)])


class TestBrandSampleReview(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.brand_sample_review import (
            context, review, apply,
        )
        for name in ("load_brand_context", "load_sample_pois"):
            self.assertTrue(hasattr(context, name),
                            f"context missing {name}")
        for name in ("review_one", "review_pois", "summarise"):
            self.assertTrue(hasattr(review, name),
                            f"review missing {name}")
        for name in ("build_unchain_rows", "apply_unchains"):
            self.assertTrue(hasattr(apply, name),
                            f"apply missing {name}")

    def test_keep_high_on_clean_bara(self):
        from dataplor_report_review.brand_sample_review.review import review_one
        ctx = {
            "name": "Tiendas Bara",
            "core_1": ["supermarket", "grocery_store"],
            "core_2": ["store", "shopping_center"],
            "business_cats": ["supermarket", "grocery_store", "store",
                              "shopping_center"],
            "domains": ["bara.com.mx"],
            "names": ["Tiendas Bara", "Tienda Bara", "Bara"],
        }
        poi = {"id": 1, "name": "Bara Los Murales", "chain": "tiendas_bara",
               "cat": "supermarket", "website": "http://bara.com.mx/",
               "provisional": False}
        v = review_one(poi, ctx)
        self.assertEqual(v["verdict"], "KEEP")
        self.assertEqual(v["confidence"], "high")

    def test_fp_unchain_on_bara_bara_fashion(self):
        from dataplor_report_review.brand_sample_review.review import review_one
        ctx = {"name": "Tiendas Bara", "core_1": [], "core_2": [],
               "business_cats": [], "domains": ["bara.com.mx"], "names": []}
        poi = {"id": 2, "name": "Tiendas Bara Bara", "chain": "tiendas_bara",
               "cat": "clothing_store", "website": "",
               "provisional": False}
        v = review_one(poi, ctx)
        self.assertEqual(v["verdict"], "FP_UNCHAIN")

    def test_corporate_office_kept_medium(self):
        from dataplor_report_review.brand_sample_review.review import review_one
        ctx = {"name": "Tiendas 3B",
               "core_1": ["supermarket"], "core_2": [],
               "business_cats": ["supermarket"],
               "domains": ["tiendas3b.com"],
               "names": ["Tiendas 3B", "Tienda 3B"]}
        poi = {"id": 3, "name": "Corporativo Tiendas 3B Guadalajara",
               "chain": "tiendas_3b", "cat": "corporate_office",
               "website": "", "provisional": False}
        v = review_one(poi, ctx)
        self.assertEqual(v["verdict"], "KEEP")

    def test_no_brand_context_is_unclear(self):
        from dataplor_report_review.brand_sample_review.review import review_one
        poi = {"id": 4, "name": "Whatever", "chain": "no_such_brand",
               "cat": "supermarket", "website": "", "provisional": False}
        v = review_one(poi, None)
        self.assertEqual(v["verdict"], "UNCLEAR")

    def test_build_unchain_rows_shapes_correctly(self):
        from dataplor_report_review.brand_sample_review.apply import (
            build_unchain_rows,
        )
        verdicts = [
            {"id": 10, "verdict": "KEEP"},
            {"id": 11, "verdict": "FP_UNCHAIN"},
            {"id": 12, "verdict": "UNCLEAR"},
            {"id": 13, "verdict": "FP_UNCHAIN"},
        ]
        rows = build_unchain_rows(verdicts)
        self.assertEqual([r["place_id"] for r in rows], [11, 13])
        for r in rows:
            self.assertEqual(r["path"], "/chain_id")
            self.assertEqual(r["value"], "")  # empty string, not None
            self.assertEqual(r["observation_type"], "ManualObservation")

    def test_apply_unchains_noop_when_no_fps(self):
        from dataplor_report_review.brand_sample_review.apply import (
            apply_unchains,
        )
        called = []
        def writer(rows, admin_id):
            called.append((rows, admin_id))
        def ptu(pids):
            called.append(("ptu", pids))
        out = apply_unchains([{"id": 1, "verdict": "KEEP"}], writer, 42476,
                              ptu_trigger=ptu)
        self.assertEqual(out["fp_count"], 0)
        self.assertEqual(called, [])

    def test_invalid_category_error_raised(self):
        """Fake conn where business_categories has only 'supermarket'.
        A brand carrying 'supermarcet' (typo) should raise
        InvalidCategoryError with the offending keys."""
        from dataplor_report_review.brand_sample_review import (
            context as ctx_mod, InvalidCategoryError,
        )

        class _FakeCursor:
            def __init__(self, outer):
                self.outer = outer; self._results = []
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def execute(self, sql, params=None):
                s = sql.strip().lower()
                if "from brands" in s:
                    # (id, key, name, c1, c2, bc)
                    self._results = [(1, "brand_x", "Brand X",
                                      ["supermarcet"], [], ["supermarket"])]
                elif "from brand_websites" in s:
                    self._results = []
                elif "from brand_names" in s:
                    self._results = []
                elif "from business_categories" in s:
                    self._results = [("supermarket",)]
                else:
                    self._results = []
            def fetchall(self):
                return list(self._results)

        class _FakeConn:
            def cursor(self): return _FakeCursor(self)

        with self.assertRaises(InvalidCategoryError) as cm:
            ctx_mod.load_brand_context(_FakeConn(), ["brand_x"])
        self.assertIn("brand_x", cm.exception.invalid)
        self.assertIn("core_1", cm.exception.invalid["brand_x"])
        self.assertEqual(cm.exception.invalid["brand_x"]["core_1"],
                         ["supermarcet"])

    def test_invalid_category_bypass_with_flag(self):
        """validate_categories=False must skip the taxonomy check."""
        from dataplor_report_review.brand_sample_review import (
            context as ctx_mod,
        )

        class _FakeCursor:
            def __init__(self): self._results = []
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def execute(self, sql, params=None):
                s = sql.strip().lower()
                if "from brands" in s:
                    self._results = [(1, "brand_x", "Brand X",
                                      ["supermarcet"], [], [])]
                elif "from brand_websites" in s:
                    self._results = []
                elif "from brand_names" in s:
                    self._results = []
                elif "from business_categories" in s:
                    self._results = [("supermarket",)]
                else:
                    self._results = []
            def fetchall(self):
                return list(self._results)

        class _FakeConn:
            def cursor(self): return _FakeCursor()

        out = ctx_mod.load_brand_context(_FakeConn(), ["brand_x"],
                                          validate_categories=False)
        self.assertEqual(out["brand_x"]["core_1"], ["supermarcet"])


class TestChain(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.chain import (
            filter, enrich, llm_review, apply, verify, retrieval_gap,
        )
        self.assertEqual(filter.DEFAULT_MIN_SCORE, 0.5)
        self.assertTrue(callable(llm_review.batch_verdict))
        for name in ("load_kuebiko_raw", "find_domain_orphans",
                     "find_name_prefix_orphans", "cross_check_official_pins",
                     "retrieval_gap_report", "write_findings_csv"):
            self.assertTrue(hasattr(retrieval_gap, name),
                            f"chain.retrieval_gap missing {name}")

    def test_retrieval_gap_norm_domain(self):
        from dataplor_report_review.chain.retrieval_gap import _norm_domain
        self.assertEqual(_norm_domain("http://www.bara.com.mx/tiendas"),
                         "bara.com.mx")
        self.assertEqual(_norm_domain("https://Tiendas3B.com/"),
                         "tiendas3b.com")
        self.assertEqual(_norm_domain(""), "")
        self.assertEqual(_norm_domain(None), "")


class TestExportQA(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.export_qa import (
            checks, verdict, act, components, from_csv,
        )
        # Client-facing garbage-name check is safe for known patterns
        self.assertTrue(callable(checks.is_client_facing_garbage_name))

    def test_client_facing_garbage_name_positives(self):
        from dataplor_report_review.export_qa.checks import (
            is_client_facing_garbage_name as g,
        )
        self.assertEqual(g("V")[0], True)
        self.assertEqual(g("Jm")[0], True)
        self.assertEqual(g("*positiveherespectreedisbyesemanubaisth*")[0], True)
        self.assertEqual(g("11-Jul")[0], True)
        self.assertEqual(g("@aye Billiard Hall")[0], True)
        self.assertEqual(g('"budget" Tapa King')[0], True)
        self.assertEqual(g("(cmea) Circuit Makati Estate Admin Office")[0], True)
        self.assertEqual(g("+81 Bar")[0], True)

    def test_client_facing_garbage_name_preserves_foreign(self):
        """CRITICAL: never treat legit non-Latin script as garbage."""
        from dataplor_report_review.export_qa.checks import (
            is_client_facing_garbage_name as g,
        )
        # Hebrew (Playst Philippines Travel Agency)
        self.assertEqual(g("פלייסט פיליפינים סוכנות נסיעות")[0], False)
        # Korean church
        self.assertEqual(g("마닐라 한인 감리 교회")[0], False)
        # Chinese restaurant
        self.assertEqual(g("威南記海南雞飯")[0], False)
        # Thai restaurant
        self.assertEqual(g("ร้านหมูกระทะ นะจ๊ะ")[0], False)
        # Vietnamese restaurant
        self.assertEqual(g("Lương Sơn Quán")[0], False)
        # Cyrillic (Russian shop)
        self.assertEqual(g("Магазин См")[0], False)
        # Devanagari (Hindi trading company)
        self.assertEqual(g("श्री नाथ ट्रेडिंग कम्पनी बाग़")[0], False)

    def test_client_facing_garbage_name_preserves_legit_short(self):
        """Real business names longer than 2 chars pass."""
        from dataplor_report_review.export_qa.checks import (
            is_client_facing_garbage_name as g,
        )
        self.assertEqual(g("7-Eleven")[0], False)
        self.assertEqual(g("K2 store")[0], False)  # K2 is a real brand
        self.assertEqual(g("121 Restaurant")[0], False)


class TestVisits(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.visits import scan, verdict, act


class TestCongruence(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.congruence import (
            db_vs_export, export_vs_postexport, three_way_report,
        )


class TestDarcCheck(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.darc_check import (
            darc_vs_ticket, darc_vs_schema, canonical_check,
        )
        self.assertTrue(canonical_check.CANONICAL_CHECK_TAB_URL.startswith("https://"))


class TestRemediate(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.remediate import (
            triage, fix, reexport,
        )
        self.assertLessEqual(fix.CONFIDENCE_CAP, 0.95)


if __name__ == "__main__":
    unittest.main()
