import unittest

import fitz

from analyzer.pdf_export import legacy_parts, memo_pdf


class PdfExportTests(unittest.TestCase):
    def test_legacy_header_is_removed_from_body(self):
        title, date, body = legacy_parts(
            "# Investment Memo: Acme\n\n**Date:** March 2, 2026\n\n---\n\n## Summary\nGood company.",
            "Fallback", "2026-01-01")
        self.assertEqual(title, "Acme")
        self.assertEqual(date, "March 2, 2026")
        self.assertNotIn("Investment Memo", body)
        self.assertNotIn("**Date:**", body)
        self.assertIn("## Summary", body)

    def test_pdf_is_valid_and_contains_header_body_and_page_number(self):
        payload = memo_pdf("Acme", "March 2, 2026", "## Decision\n\n**INVEST** because evidence supports it.\n\n- Risk remains.")
        document = fitz.open(stream=payload, filetype="pdf")
        text = "\n".join(page.get_text() for page in document)
        self.assertGreater(len(payload), 1000)
        self.assertIn("Acme", text)
        self.assertIn("Analyzed March 2, 2026", text)
        self.assertIn("Decision", text)
        self.assertIn("Investment Analyzer", text)
        self.assertIn("1", text)
        document.close()


if __name__ == "__main__":
    unittest.main()
