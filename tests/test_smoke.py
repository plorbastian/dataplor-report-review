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


class TestChain(unittest.TestCase):
    def test_public_surface(self):
        from dataplor_report_review.chain import (
            filter, enrich, llm_review, apply, verify,
        )
        self.assertEqual(filter.DEFAULT_MIN_SCORE, 0.5)
        self.assertTrue(callable(llm_review.batch_verdict))


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
