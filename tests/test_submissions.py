import base64
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

from analyzer.pipeline import Jobs
from analyzer.storage import Repository, document_fingerprint


def doc(name, text):
    return {"name": name, "data": base64.b64encode(text.encode()).decode()}


class SubmissionTests(unittest.TestCase):
    def test_fingerprint_ignores_names_order_and_repeated_files(self):
        self.assertEqual(document_fingerprint([doc("a", "one"), doc("b", "two")]),
                         document_fingerprint([doc("renamed", "two"), doc("c", "one"), doc("c", "one")]))
        self.assertNotEqual(document_fingerprint([doc("a", "one")]), document_fingerprint([doc("a", "changed")]))

    def test_simultaneous_duplicate_submissions_create_one_record(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(root=directory)
            manager = Jobs()
            with patch.object(manager, "start", return_value=True):
                def submit(_):
                    return manager.submit("local", repo, {"company_name": "Test", "model": "test"}, [doc("deck", "contents")], "fake", None)
                with ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(submit, range(2)))
            self.assertEqual(len(repo.list()), 1)
            self.assertEqual(sum(created for _, created in results), 1)
            self.assertEqual(results[0][0]["id"], results[1][0]["id"])

    def test_queue_waits_and_cancelled_work_never_executes(self):
        with tempfile.TemporaryDirectory() as directory:
            repo, manager = Repository(root=directory), Jobs()
            entered, release, second_started = threading.Event(), threading.Event(), threading.Event()
            first = repo.create({"company_name": "First", "model": "test"}, [])
            second = repo.create({"company_name": "Second", "model": "test"}, [])
            def execute():
                entered.set()
                release.wait(3)
            p1 = SimpleNamespace(repo=repo, state=first, cancel=threading.Event(), execute=execute)
            p2 = SimpleNamespace(repo=repo, state=second, cancel=threading.Event(), execute=second_started.set)
            try:
                manager.start(("local", first["id"]), p1)
                self.assertTrue(entered.wait(1))
                manager.start(("local", second["id"]), p2)
                self.assertEqual(repo.load(second["id"])["status"], "queued")
                self.assertFalse(second_started.is_set())
                manager.stop(("local", second["id"]))
                manager.items[("local", second["id"])][0].join(1)
                self.assertEqual(repo.load(second["id"])["status"], "cancelled")
                self.assertFalse(second_started.is_set())
            finally:
                release.set()
                manager.items[("local", first["id"])][0].join(1)


if __name__ == "__main__":
    unittest.main()
