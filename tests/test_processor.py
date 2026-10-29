import json, os, sys, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
import processor
from fakes import FakeS3


def gemini(payload):
    return {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}}]}


def event(key):
    return {"Records": [{"s3": {"bucket": {"name": "b"}, "object": {"key": key}}}]}


class ParseTests(unittest.TestCase):
    def test_valid(self):
        r = processor.parse_response(gemini({"category": "Invoice", "summary": "Bill.", "keywords": ["a", "b"]}))
        self.assertEqual(r["category"], "Invoice")
        self.assertEqual(r["keywords"], ["a", "b"])

    def test_unknown_category_falls_back(self):
        r = processor.parse_response(gemini({"category": "Spaceship", "summary": "x"}))
        self.assertEqual(r["category"], "Other")
        self.assertEqual(r["keywords"], [])

    def test_bad_json_and_missing_summary(self):
        with self.assertRaises(processor.ProcessingError):
            processor.parse_response({"candidates": [{"content": {"parts": [{"text": "not json"}]}}]})
        with self.assertRaises(processor.ProcessingError):
            processor.parse_response(gemini({"category": "Report", "summary": "  "}))
        with self.assertRaises(processor.ProcessingError):
            processor.parse_response({})

    def test_build_parts_edge_cases(self):
        with self.assertRaises(processor.ProcessingError):
            processor.build_parts("uploads/a__x.txt", b"")
        with self.assertRaises(processor.ProcessingError):
            processor.build_parts("uploads/a__x.txt", b"   \n")
        with self.assertRaises(processor.ProcessingError):
            processor.build_parts("uploads/a__x.exe", b"MZ")
        self.assertIn("inline_data", processor.build_parts("uploads/a__x.pdf", b"%PDF")[0])


class HandlerTests(unittest.TestCase):
    def run_handler(self, files, key, **patch_kw):
        fake = FakeS3(files)
        with patch.object(processor, "s3", fake), patch.object(processor, "call_gemini", **patch_kw) as g:
            out = processor.lambda_handler(event(key))
        return fake, g, out

    def test_success_writes_processed_json(self):
        ok = gemini({"category": "Report", "summary": "Quarterly numbers.", "keywords": ["q3"]})
        fake, _, out = self.run_handler({"uploads/abc__note.txt": b"hello"}, "uploads/abc__note.txt", return_value=ok)
        doc = json.loads(fake.files["processed/abc.json"])
        self.assertEqual((out["processed"], doc["status"], doc["filename"]), (["processed"], "processed", "note.txt"))

    def test_gemini_failure_writes_failed_json(self):
        fake, _, _ = self.run_handler({"uploads/abc__n.txt": b"hi"}, "uploads/abc__n.txt",
                                      side_effect=processor.ProcessingError("Gemini API error 503"))
        doc = json.loads(fake.files["failed/abc.json"])
        self.assertEqual((doc["status"], doc["error"]), ("failed", "Gemini API error 503"))
        self.assertNotIn("processed/abc.json", fake.files)

    def test_unexpected_error_is_contained(self):
        fake, _, _ = self.run_handler({"uploads/abc__n.txt": b"hi"}, "uploads/abc__n.txt", side_effect=RuntimeError("boom"))
        self.assertEqual(json.loads(fake.files["failed/abc.json"])["error"], "Unexpected processing error")

    def test_unsupported_and_empty_files_fail_without_calling_gemini(self):
        for name, data in (("x.exe", b"MZ"), ("x.txt", b"")):
            fake, g, _ = self.run_handler({f"uploads/abc__{name}": data}, f"uploads/abc__{name}")
            g.assert_not_called()
            self.assertIn("failed/abc.json", fake.files)

    def test_oversize_file_rejected(self):
        with patch.object(processor, "MAX_BYTES", 3):
            fake, g, _ = self.run_handler({"uploads/abc__n.txt": b"too big"}, "uploads/abc__n.txt")
        g.assert_not_called()
        self.assertIn("larger than", json.loads(fake.files["failed/abc.json"])["error"])

    def test_idempotent_redelivery_is_skipped(self):
        files = {"uploads/abc__n.txt": b"hi", "processed/abc.json": b"{}"}
        _, g, out = self.run_handler(files, "uploads/abc__n.txt")
        g.assert_not_called()
        self.assertEqual(out["processed"], ["skipped"])

    def test_url_encoded_keys_and_foreign_prefixes(self):
        ok = gemini({"category": "Other", "summary": "s"})
        fake, _, _ = self.run_handler({"uploads/abc__my file.txt": b"hi"}, "uploads/abc__my+file.txt", return_value=ok)
        self.assertEqual(json.loads(fake.files["processed/abc.json"])["filename"], "my file.txt")
        _, g, out = self.run_handler({}, "processed/abc.json")
        self.assertEqual(out["processed"], [])


if __name__ == "__main__":
    unittest.main()
