import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from uuid import uuid4

from analyzer.storage import Repository


class DeletionTests(unittest.TestCase):
    def test_only_selected_local_record_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            repo = Repository(root=Path(directory) / "runs")
            first = repo.create({"company_name": "First", "model": "test"}, [])
            second = repo.create({"company_name": "Second", "model": "test"}, [])
            repo.delete(first["id"])
            self.assertIsNone(repo.load(first["id"]))
            self.assertIsNotNone(repo.load(second["id"]))
            with self.assertRaises(ValueError):
                repo.delete("../../other-file")

    def test_legacy_deletion_confined_to_history(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            history = root / "history"
            history.mkdir()
            repo = Repository(root=history / "runs")
            memo = history / "old.md"
            memo.write_text("legacy memo")
            outside = root / "private.md"
            outside.write_text("not a memo")
            with self.assertRaises(ValueError):
                repo.delete_legacy(str(outside))
            link = history / "link.md"
            link.symlink_to(outside)
            with self.assertRaises(ValueError):
                repo.delete_legacy(str(link))
            repo.delete_legacy(str(memo))
            self.assertFalse(memo.exists())
            self.assertTrue(outside.exists())

    def test_cloud_delete_filters_owner_and_id(self):
        client = MagicMock()
        query = client.table.return_value.delete.return_value
        query.eq.return_value = query
        identifier = str(uuid4())
        Repository(client=client, owner="alice").delete(identifier)
        self.assertEqual([call.args for call in query.eq.call_args_list], [("id", identifier), ("owner_id", "alice")])
        query.execute.assert_called_once()


if __name__ == "__main__":
    unittest.main()
