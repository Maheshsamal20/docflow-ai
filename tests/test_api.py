import json, os, sys, unittest
from unittest.mock import patch
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
sys.path.insert(0, os.path.dirname(__file__))
os.environ["BUCKET"] = "test-bucket"
import api
from fakes import FakeS3
from gemini_client import ProcessingError


def call(route, body=None, path=None):
    return api.lambda_handler({"routeKey": route, "body": body, "pathParameters": path})


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeS3()
        p = patch.object(api, "s3", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def test_upload_url_ok(self):
        r = call("POST /upload-url", json.dumps({"filename": "My Report.pdf"}))
        body = json.loads(r["body"])
        self.assertEqual(r["statusCode"], 200)
        self.assertEqual(body["contentType"], "application/pdf")
        self.assertTrue(body["key"].startswith("uploads/") and body["key"].endswith("__My_Report.pdf"))

    def test_upload_url_rejects_bad_input(self):
        self.assertEqual(call("POST /upload-url", json.dumps({"filename": "a.exe"}))["statusCode"], 400)
        self.assertEqual(call("POST /upload-url", "{nope")["statusCode"], 400)
        self.assertEqual(call("POST /upload-url", None)["statusCode"], 400)
        self.assertEqual(call("POST /upload-url", "[1]")["statusCode"], 400)

    def test_path_traversal_filename_is_sanitized(self):
        r = call("POST /upload-url", json.dumps({"filename": "../../etc/passwd.txt"}))
        self.assertNotIn("..", json.loads(r["body"])["key"].split("__", 1)[1][:2])
        self.assertEqual(r["statusCode"], 200)

    def test_get_document(self):
        self.fake.files["processed/abc.json"] = json.dumps({"id": "abc", "status": "processed"}).encode()
        self.assertEqual(call("GET /documents/{id}", path={"id": "abc"})["statusCode"], 200)
        self.assertEqual(call("GET /documents/{id}", path={"id": "zzz"})["statusCode"], 404)
        self.assertEqual(call("GET /documents/{id}", path={"id": "../x"})["statusCode"], 400)

    def test_list_includes_pending_and_finished(self):
        self.fake.files["uploads/new1__a.txt"] = b"x"
        self.fake.files["uploads/old1__b.txt"] = b"x"
        self.fake.files["processed/old1.json"] = json.dumps({"id": "old1", "status": "processed", "processed_at": "2026"}).encode()
        docs = json.loads(call("GET /documents")["body"])["documents"]
        self.assertEqual([(d["id"], d["status"]) for d in docs], [("new1", "processing"), ("old1", "processed")])

    def test_unknown_route(self):
        self.assertEqual(call("DELETE /documents")["statusCode"], 404)


class AskTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeS3({
            "uploads/abc__n.txt": b"The invoice total is 450 dollars, due 5 May.",
            "processed/abc.json": json.dumps({"id": "abc", "status": "processed", "key": "uploads/abc__n.txt"}).encode()})
        p = patch.object(api, "s3", self.fake)
        p.start()
        self.addCleanup(p.stop)

    def ask(self, **payload):
        return api.lambda_handler({"routeKey": "POST /ask", "body": json.dumps(payload)})

    def test_answer(self):
        reply = {"candidates": [{"content": {"parts": [{"text": " 450 dollars. "}]}}]}
        with patch.object(api, "call_gemini", return_value=reply) as g:
            r = self.ask(id="abc", question="What is the total?")
        self.assertEqual((r["statusCode"], json.loads(r["body"])["answer"]), (200, "450 dollars."))
        self.assertIn("What is the total?", g.call_args[0][0])

    def test_validation(self):
        self.assertEqual(self.ask(id="abc", question="  ")["statusCode"], 400)
        self.assertEqual(self.ask(id="abc", question="x" * 501)["statusCode"], 400)
        self.assertEqual(self.ask(id="../x", question="hi")["statusCode"], 400)
        self.assertEqual(api.lambda_handler({"routeKey": "POST /ask", "body": "{bad"})["statusCode"], 400)

    def test_not_ready_or_source_missing(self):
        self.assertEqual(self.ask(id="nope", question="hi")["statusCode"], 404)
        del self.fake.files["uploads/abc__n.txt"]
        self.assertEqual(self.ask(id="abc", question="hi")["statusCode"], 404)

    def test_gemini_failure_returns_502(self):
        with patch.object(api, "call_gemini", side_effect=ProcessingError("Gemini API error 503")):
            r = self.ask(id="abc", question="hi")
        self.assertEqual(r["statusCode"], 502)
        self.assertIn("503", json.loads(r["body"])["error"])


if __name__ == "__main__":
    unittest.main()
