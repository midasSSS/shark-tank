import os
import tempfile
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest

from analyzer.finance import calculate
from analyzer.pipeline import Pipeline
from analyzer.storage import Repository
from test_analyzer import economics, assessment


class UITests(unittest.TestCase):
    def test_upload_only_form_and_missing_file_validation(self):
        with patch.dict(os.environ, {"LOCAL_MODE": "1"}):
            app = AppTest.from_file("run.py").run(timeout=20)
            self.assertFalse(app.exception)
            self.assertEqual(app.title[0].value, "Investment Analyzer")
            self.assertNotIn("Sign in", [button.label for button in app.button])
            next(button for button in app.button if button.label == "Analyze investment").click().run()
            self.assertTrue(any("Upload at least one file" in message.value for message in app.error))
            self.assertFalse(app.text_input)
            self.assertFalse(app.text_area)
            self.assertFalse(app.selectbox)
            self.assertFalse(app.number_input)

    def test_completed_result_and_sensitivity(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict(os.environ, {"LOCAL_MODE": "1"}):
            repo = Repository(root=temp)
            state = repo.create({"company_name": "Synthetic UI Fixture", "model": "fixture"}, [])
            calc = calculate(economics())
            decision = dict(reasons=["The synthetic market outcome supports the required exit."], main_risk="Execution",
                            confidence="medium", confidence_reason="Synthetic fixture", source_ids=["input-terms"])
            state["steps"] = {"economics": economics(), "calculation": calc, "evidence": {"facts": []}}
            state["status"] = "complete"
            state["result"] = dict(verdict="INVEST", basis="100× potential", decision=decision,
                                   hundred=assessment(), defensive=assessment(False),
                                   summary=Pipeline.render("INVEST", "100× potential", [], decision, calc))
            repo.save(state)
            with patch("analyzer.ui.Repository", return_value=repo):
                app = AppTest.from_file("run.py")
                app.session_state["active_run"] = state["id"]
                app.run(timeout=20)
                self.assertFalse(app.exception)
                self.assertTrue(any("INVEST" in markdown.value for markdown in app.markdown))
                self.assertTrue(any("100×" in metric.label for metric in app.metric))
                self.assertIn("Delete analysis", [button.label for button in app.button])
                self.assertIn("Save as PDF", [button.label for button in app.get("download_button")])

    def test_cloud_mode_requires_configuration(self):
        with patch.dict(os.environ, {"LOCAL_MODE": "0"}):
            # Test the configuration gate without contacting any cloud account.
            import run
            with patch.object(run, "is_supabase_enabled", return_value=False):
                from analyzer.ui import main
                from types import SimpleNamespace
                fake = SimpleNamespace(is_supabase_enabled=lambda: False)
                with patch("streamlit.set_page_config"), patch("streamlit.title"), patch("streamlit.caption"), patch("streamlit.error") as error:
                    main(fake)
                    error.assert_called_once()


if __name__ == "__main__":
    unittest.main()
