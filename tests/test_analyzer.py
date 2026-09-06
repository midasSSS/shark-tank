import base64
import io
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import fitz
from openpyxl import Workbook

from analyzer.finance import calculate, verdict
from analyzer.ingestion import extract
from analyzer.models import Decision, Economics, Evidence, EvidenceReview, PathAssessment
from analyzer.pipeline import Pipeline, RequestBudgetExceeded
from analyzer.storage import Repository


def economics(**updates):
    values = dict(supported=True, instrument="simple_equity", currency="USD", entry_post_money=20_000_000,
                  investment=100_000, retained_fraction=.5, fee_fraction=0, carry_fraction=0, holding_years=10,
                  exit_downside=10_000_000, exit_base=100_000_000, exit_upside=4_000_000_000,
                  source_ids=["input-terms"], assumptions=["Illustrative future dilution"], limitations=[])
    values.update(updates)
    return values


def assessment(qualifies=True):
    return dict(qualifies=qualifies, reasons=["Supported unit economics and a plausible market outcome."],
                source_ids=["input-terms"], required_outcome="A $4bn equity exit.", main_risk="Execution risk", blockers=[])


class FinanceTests(unittest.TestCase):
    def test_reverse_100x_and_ownership(self):
        result = calculate(economics())
        self.assertEqual(result["required_exit_for_100x"], 4_000_000_000)
        self.assertEqual(result["scenarios"]["upside"]["net_moic"], 100)
        self.assertEqual(result["initial_ownership"], .005)
        self.assertEqual(result["scenarios"]["upside"]["net_proceeds"], 10_000_000)

    def test_fees_carry_reconcile_target(self):
        inputs = economics(fee_fraction=.02, carry_fraction=.2)
        target = calculate(inputs)["required_exit_for_100x"]
        result = calculate(dict(inputs, exit_upside=target))
        self.assertAlmostEqual(result["scenarios"]["upside"]["net_moic"], 100)
        loss = calculate(dict(inputs, exit_downside=0))["scenarios"]["downside"]
        self.assertEqual(loss["net_moic"], 0)
        self.assertEqual(loss["annualized_return"], -1)

    def test_unknown_and_unsupported_terms(self):
        for changes in ({"entry_post_money": None}, {"instrument": "unsupported"}, {"supported": False},
                        {"retained_fraction": 0}, {"carry_fraction": 1}, {"entry_post_money": float('inf')},
                        {"exit_base": -1}, {"exit_downside": 200_000_000}, {"investment": -1}):
            with self.subTest(changes=changes):
                self.assertFalse(calculate(economics(**changes))["supported"])

    def test_safe_scope(self):
        self.assertTrue(calculate(economics(instrument="post_money_safe"))["supported"])
        self.assertFalse(calculate(economics(limitations=["Conversion basis unknown"]))["supported"])

    def test_verdict_requires_real_path(self):
        yes, no = assessment(), assessment(False)
        calc = calculate(economics())
        self.assertEqual(verdict(yes, no, calc, [], "medium")[0], "INVEST")
        self.assertEqual(verdict(no, yes, calc, [], "high")[0], "PASS")
        self.assertEqual(verdict(no, no, calc, [], "high")[0], "PASS")
        self.assertEqual(verdict(yes, yes, calc, ["Missing material terms"], "high")[0], "PASS")
        self.assertEqual(verdict(yes, yes, calc, [], "low")[0], "PASS")
        defensive = calculate(economics(exit_downside=40_000_000))
        self.assertEqual(verdict(no, yes, defensive, [], "high")[:2], ("INVEST", "Downside protection"))
        expensive = calculate(economics(entry_post_money=200_000_000))
        self.assertEqual(verdict(yes, no, expensive, [], "high")[0], "PASS")


class IngestionTests(unittest.TestCase):
    def test_full_text_beyond_old_limit(self):
        text = "First page material. " * 2000 + "FINAL_CRITICAL_TERM"
        sources, gaps = extract("long.txt", text.encode())
        self.assertEqual("".join(s["text"] for s in sources), text)
        self.assertIn("FINAL_CRITICAL_TERM", sources[-1]["text"])
        self.assertFalse(gaps)

    def test_pdf_page_provenance_and_blank_page_gap(self):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Revenue was USD 5 million for the fiscal year 2025. This is company reported.")
        doc.new_page()
        sources, gaps = extract("fixture.pdf", doc.tobytes())
        doc.close()
        self.assertEqual(sources[0]["location"], "page-1")
        self.assertTrue(any("page" in gap for gap in gaps))

    def test_csv_preserves_header_and_late_rows(self):
        data = "period,revenue\n" + "\n".join(f"{i},100" for i in range(230))
        sources, gaps = extract("metrics.csv", data.encode())
        self.assertEqual(len(sources), 3)
        self.assertIn("period | revenue", sources[-1]["text"])
        self.assertIn("229 | 100", sources[-1]["text"])

    def test_xlsx_missing_formula_cache_disclosed(self):
        book = Workbook()
        sheet = book.active
        sheet.append(["Metric", "Value"])
        sheet.append(["Revenue", "=1+2"])
        stream = io.BytesIO()
        book.save(stream)
        sources, gaps = extract("financials.xlsx", stream.getvalue())
        self.assertTrue(sources)
        self.assertTrue(any("no cached value" in gap for gap in gaps))


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.repo = Repository(root=self.tmp.name)
        self.state = self.repo.create({"company_name": "Synthetic Co", "terms": "Entry valuation USD 20000000 simple equity.",
                                       "description": "", "stage": "Early stage", "business_model": "software",
                                       "thesis": "100x or downside protection", "model": "test"}, [])

    def tearDown(self):
        self.tmp.cleanup()

    def pipeline(self):
        pipe = Pipeline(self.repo, self.state, "fake", None, client=object())
        pipe.research = lambda: {"sources": [{"id": "web-1", "text": "Synthetic Co makes software.", "kind": "web",
                                              "title": "Synthetic Co", "location": "page", "url": "https://example.com"}], "gaps": []}
        def ask(role, payload, schema):
            if schema is Evidence:
                return {"facts": [{"claim": s["text"], "value": None, "unit": "", "period": "", "definition": "",
                                   "source_id": s["id"], "quote": s["text"], "status": "reported"} for s in payload["sources"]], "gaps": [], "conflicts": []}
            if schema is Economics:
                return economics()
            if schema is PathAssessment:
                return assessment("100×" in role)
            if schema is EvidenceReview:
                return {"identity_confirmed": True, "material_gaps": [], "unresolved_conflicts": [], "rationale": "Synthetic sources match."}
            if schema is Decision:
                return {"reasons": ["The required exit is supported by the supplied market scenario."],
                        "main_risk": "Execution and future financing.", "confidence": "medium",
                        "confidence_reason": "Terms and business evidence available.", "source_ids": ["input-terms"]}
            raise AssertionError(schema)
        pipe.ask = ask
        return pipe

    def test_complete_short_verdict_and_cached_resume(self):
        pipe = self.pipeline()
        pipe.execute()
        saved = self.repo.load(self.state["id"])
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(saved["result"]["verdict"], "INVEST")
        self.assertLess(len(saved["result"]["summary"].split()), 150)
        pipe.ask = lambda *args: self.fail("Completed steps must be reused")
        pipe.execute()
        self.assertEqual(self.state["status"], "complete")

    def test_failed_research_yields_pass(self):
        pipe = self.pipeline()
        pipe.research = lambda: {"sources": [], "gaps": ["Research unavailable"]}
        pipe.execute()
        self.assertEqual(self.state["result"]["verdict"], "PASS")

    def test_wrong_company_or_conflicting_terms_block_invest(self):
        pipe = self.pipeline()
        working = pipe.ask
        def review_failure(role, payload, schema):
            if schema is EvidenceReview:
                return {"identity_confirmed": False, "material_gaps": [], "unresolved_conflicts": ["Different issuers share the same name."], "rationale": "Identity mismatch"}
            return working(role, payload, schema)
        pipe.ask = review_failure
        pipe.execute()
        self.assertEqual(self.state["result"]["verdict"], "PASS")

    def test_model_schema_retry_and_budget(self):
        outputs = iter(["invalid json", '{"facts": [], "gaps": [], "conflicts": []}'])
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
            content=[SimpleNamespace(type="text", text=next(outputs))], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=10, output_tokens=5))))
        self.state["inputs"]["max_requests"] = 2
        pipe = Pipeline(self.repo, self.state, "fake", None, client=client)
        self.assertEqual(pipe.ask("Test schema", {}, Evidence)["facts"], [])
        self.assertEqual(self.state["request_count"], 2)
        with self.assertRaises(RequestBudgetExceeded):
            pipe.ask("Test budget", {}, Evidence)

    def test_model_json_wrapper_is_recovered(self):
        client = SimpleNamespace(messages=SimpleNamespace(create=lambda **kwargs: SimpleNamespace(
            content=[SimpleNamespace(type="text", text='Here is the result: {"facts": [], "gaps": [], "conflicts": []}')],
            stop_reason="end_turn", usage=SimpleNamespace(input_tokens=10, output_tokens=5))))
        pipe = Pipeline(self.repo, self.state, "fake", None, client=client)
        self.assertEqual(pipe.ask("Test wrapped schema", {}, Evidence)["facts"], [])
        self.assertEqual(self.state["request_count"], 1)

    def test_summary_length_and_markdown_injection(self):
        decision = {"reasons": ["word " * 200 + "![tracking](https://example.com)"], "main_risk": "risk " * 60,
                    "confidence": "medium", "confidence_reason": "detail " * 50}
        summary = Pipeline.render("INVEST", "100× potential", [], decision, calculate(economics()))
        self.assertLessEqual(len(summary.split()), 150)
        decision["reasons"] = ["![tracking](https://example.com)"]
        summary = Pipeline.render("PASS", "Neither established", [], decision, {})
        self.assertNotIn("![tracking]", summary)

    def test_failure_checkpoint_and_retry(self):
        pipe = self.pipeline()
        working = pipe.ask
        def fail_financial(role, payload, schema):
            if schema is Economics:
                raise TimeoutError("secret body must never appear in storage")
            return working(role, payload, schema)
        pipe.ask = fail_financial
        pipe.execute()
        self.assertEqual(self.state["status"], "failed")
        self.assertTrue(any(key.startswith("extract:") for key in self.state["steps"]))
        self.assertNotIn("secret body", json.dumps(self.state))
        pipe.ask = working
        pipe.execute()
        self.assertEqual(self.state["status"], "complete")

    def test_cancellation_retains_state(self):
        pipe = self.pipeline()
        pipe.cancel.set()
        pipe.execute()
        self.assertEqual(self.state["status"], "cancelled")
        self.assertNotIn("result", self.state)

    def test_fake_quote_rejected(self):
        result = {"facts": [{"source_id": "web-1", "quote": "invented", "status": "reported"}], "gaps": [], "conflicts": []}
        checked = Pipeline.verified_evidence(result, {"id": "web-1", "text": "Actual reported fact"})
        self.assertFalse(checked["facts"])
        self.assertTrue(checked["validation_errors"])

    def test_local_record_and_legacy_compatibility(self):
        self.assertEqual(self.repo.load(self.state["id"])["company_name"], "Synthetic Co")
        self.assertEqual(len(self.repo.list()), 1)
        self.assertIsNone(self.repo.decode("# Old investment memo"))
        self.assertEqual((Path(self.tmp.name) / f"{self.state['id']}.json").stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            self.repo.load("../../other-user")
        with self.assertRaises(ValueError):
            Repository(client=object())

    def test_cloud_queries_enforce_owner_for_load_list_and_save(self):
        rows = [{"id": "one", "owner_id": "alice", "company_name": "A", "created_at": "2026-01-01", "memo_content": json.dumps(self.state)},
                {"id": "two", "owner_id": "bob", "company_name": "B", "created_at": "2026-01-01", "memo_content": json.dumps(self.state)}]
        class Query:
            def __init__(self):
                self.filters, self.updates = {}, None
            def select(self, fields):
                return self
            def eq(self, key, value):
                self.filters[key] = value
                return self
            def limit(self, value):
                return self
            def order(self, *args, **kwargs):
                return self
            def update(self, updates):
                self.updates = updates
                return self
            def execute(self):
                matched = [row for row in rows if all(row.get(k) == v for k, v in self.filters.items())]
                for row in matched:
                    if self.updates:
                        row.update(self.updates)
                return SimpleNamespace(data=matched)
        repo = Repository(client=SimpleNamespace(table=lambda table: Query()), owner="alice")
        self.assertIsNotNone(repo.load("one"))
        self.assertIsNone(repo.load("two"))
        self.assertEqual([row["id"] for row in repo.list()], ["one"])
        original = rows[1]["memo_content"]
        repo.save(dict(self.state, id="two"))
        self.assertEqual(rows[1]["memo_content"], original)

    def test_search_queries_exclude_private_terms(self):
        class Search:
            queries = []
            def search(self, **kwargs):
                self.queries.append(kwargs["query"])
                return {"results": []}
        search = Search()
        pipe = Pipeline(self.repo, self.state, "fake", None, client=object(), search=search)
        pipe.research()
        self.assertEqual(len(search.queries), 2)
        self.assertFalse(any("20000000" in query for query in search.queries))


if __name__ == "__main__":
    unittest.main()
