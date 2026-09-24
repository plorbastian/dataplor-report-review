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
            merge_push, sample_cleanup, verify,
        )
        # Guard has the category families
        self.assertGreaterEqual(len(guard.CATEGORY_FAMILIES), 5)
        # Safety exposes the rejection function
        self.assertTrue(callable(safety.safety_reject))
        # Strict has the component builder
        self.assertTrue(callable(strict.build_components))


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
