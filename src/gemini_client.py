"""Shared Gemini helpers. Standard library only, so no Lambda layer is needed."""
import base64
import json
import os
import time
import urllib.error
import urllib.request

TEXT_EXT = {".txt", ".md", ".csv", ".json", ".log"}
BINARY_MIME = {".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}
MAX_CHARS = 100_000


class ProcessingError(Exception):
    """A failure we understand and can show to the user."""


def build_parts(key, data):
    ext = os.path.splitext(key)[1].lower()
    if not data:
        raise ProcessingError("File is empty")
    if ext in TEXT_EXT:
        text = data.decode("utf-8", errors="replace").strip()
        if not text:
            raise ProcessingError("File has no readable text")
        return [{"text": "DOCUMENT:\n" + text[:MAX_CHARS]}]
    if ext in BINARY_MIME:
        return [{"inline_data": {"mime_type": BINARY_MIME[ext], "data": base64.b64encode(data).decode()}}]
    raise ProcessingError(f"Unsupported file type '{ext or 'none'}'")


def call_gemini(prompt, parts, json_mode=True, attempts=3, timeout=30):
    model = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    config = {"temperature": 0.2}
    if json_mode:
        config["responseMimeType"] = "application/json"
    body = json.dumps({"contents": [{"parts": [{"text": prompt}] + parts}], "generationConfig": config}).encode()
    headers = {"Content-Type": "application/json", "x-goog-api-key": os.environ.get("GEMINI_API_KEY", "")}
    for i in range(attempts):
        try:
            req = urllib.request.Request(url, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503, 504) and i < attempts - 1:
                time.sleep(2 ** i)
                continue
            raise ProcessingError(f"Gemini API error {e.code}")
        except (urllib.error.URLError, TimeoutError):
            if i < attempts - 1:
                time.sleep(2 ** i)
                continue
            raise ProcessingError("Gemini API unreachable")


def extract_text(resp):
    try:
        return resp["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError):
        raise ProcessingError("Gemini returned an unusable response")
