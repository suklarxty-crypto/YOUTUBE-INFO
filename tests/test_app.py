import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("API_KEYS", "TESTKEY")

import app as api


class AppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        api.API_KEYS = {"TESTKEY"}
        cls.client = api.app.test_client()

    def test_home(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        body = r.get_json()
        self.assertEqual(body["status"], "ok")
        self.assertIn("/yt", body["endpoints"])

    def test_ping(self):
        r = self.client.get("/ping")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_data(as_text=True), "pong")

    def test_health(self):
        r = self.client.get("/health")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.get_json()["status"], "healthy")

    def test_invalid_endpoint(self):
        r = self.client.get("/does-not-exist")
        self.assertEqual(r.status_code, 404)
        self.assertEqual(r.get_json()["error_code"], "NOT_FOUND")

    def test_missing_key(self):
        r = self.client.get("/yt?url=https://youtu.be/dQw4w9WgXcQ")
        self.assertEqual(r.status_code, 401)
        self.assertEqual(r.get_json()["error_code"], "MISSING_API_KEY")

    def test_invalid_key(self):
        r = self.client.get("/yt?url=https://youtu.be/dQw4w9WgXcQ&key=BAD")
        self.assertEqual(r.status_code, 403)
        self.assertEqual(r.get_json()["error_code"], "INVALID_API_KEY")

    def test_invalid_url(self):
        r = self.client.get("/yt?url=https://example.com/x&key=TESTKEY")
        self.assertEqual(r.status_code, 400)
        self.assertEqual(r.get_json()["error_code"], "INVALID_URL")

    def test_valid_youtube_url_parser(self):
        ok, vid = api.validate_youtube_url("https://youtu.be/dQw4w9WgXcQ?t=10")
        self.assertTrue(ok)
        self.assertEqual(vid, "dQw4w9WgXcQ")

    def test_quality_fallback(self):
        self.assertEqual(api.validate_quality("not-a-quality"), "720p")
        self.assertEqual(api.validate_quality("1080p"), "1080p")


if __name__ == "__main__":
    unittest.main(verbosity=2)
