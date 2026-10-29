import io, os, sys, unittest, urllib.error
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import gemini_client as gc


def http_error(code):
    return urllib.error.HTTPError("https://x", code, "err", {}, None)


class ClientTests(unittest.TestCase):
    def setUp(self):
        os.environ["GEMINI_API_KEY"] = "test"
        p = patch.object(gc.time, "sleep")
        p.start()
        self.addCleanup(p.stop)

    def call(self, effects):
        with patch.object(gc.urllib.request, "urlopen", side_effect=effects) as u:
            try:
                return gc.call_gemini("p", []), u.call_count
            except gc.ProcessingError as e:
                return e, u.call_count

    def test_retries_then_succeeds(self):
        out, n = self.call([http_error(503), io.BytesIO(b'{"ok": 1}')])
        self.assertEqual((out, n), ({"ok": 1}, 2))

    def test_client_error_is_not_retried(self):
        out, n = self.call([http_error(400)])
        self.assertEqual((str(out), n), ("Gemini API error 400", 1))

    def test_gives_up_after_three_attempts(self):
        out, n = self.call([http_error(429)] * 3)
        self.assertEqual((str(out), n), ("Gemini API error 429", 3))

    def test_network_failure(self):
        out, n = self.call([urllib.error.URLError("down")] * 3)
        self.assertEqual((str(out), n), ("Gemini API unreachable", 3))

    def test_extract_text(self):
        self.assertEqual(gc.extract_text({"candidates": [{"content": {"parts": [{"text": "hi"}]}}]}), "hi")
        with self.assertRaises(gc.ProcessingError):
            gc.extract_text({"candidates": []})


if __name__ == "__main__":
    unittest.main()
