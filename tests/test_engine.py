import unittest
import os
import tempfile
import json
from unittest.mock import patch, MagicMock
import indexnow_engine

class TestIndexNowEngine(unittest.TestCase):
    def test_state_management(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            test_state_file = os.path.join(tmpdir, "state.json")
            with patch("indexnow_engine.STATE_FILE", test_state_file):
                state = indexnow_engine.load_state()
                self.assertIn("submitted", state)
                state["submitted"]["https://aviperera.com/test-post/"] = {
                    "title": "Test Post",
                    "modified": "2026-10-22T00:00:00Z"
                }
                indexnow_engine.save_state(state)
                reloaded = indexnow_engine.load_state()
                self.assertIn("https://aviperera.com/test-post/", reloaded["submitted"])

    @patch("urllib.request.urlopen")
    def test_submit_indexnow_payload(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.getcode.return_value = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp
        
        result = indexnow_engine.submit_indexnow(
            host="aviperera.com",
            key="testkey123",
            key_location="https://aviperera.com/testkey123.txt",
            url_list=["https://aviperera.com/post-1/"]
        )
        self.assertTrue(result)
        self.assertTrue(mock_urlopen.called)

if __name__ == "__main__":
    unittest.main()
