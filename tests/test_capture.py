import os
import tempfile
import time
import unittest

from screencatch import capture


class ResponseTests(unittest.TestCase):
    def test_request_object_path(self):
        self.assertEqual(
            capture.request_object_path(":1.42", "tok"),
            "/org/freedesktop/portal/desktop/request/1_42/tok",
        )

    def test_success_returns_local_path(self):
        self.assertEqual(capture.interpret_response(0, {"uri": "file:///tmp/a%20b.png"}), "/tmp/a b.png")

    def test_success_without_uri_is_error(self):
        with self.assertRaises(capture.CaptureError):
            capture.interpret_response(0, {})

    def test_cancelled(self):
        with self.assertRaises(capture.CaptureCancelled):
            capture.interpret_response(1, {})

    def test_other_codes_mean_missing_permission(self):
        with self.assertRaises(capture.CapturePermissionError) as ctx:
            capture.interpret_response(2, {})
        self.assertNotIsInstance(ctx.exception, capture.CaptureCancelled)

    def test_permission_from_lookup(self):
        permissions = {"io.example.App": ["yes"], "other": ["no"]}
        self.assertEqual(capture.permission_from_lookup(permissions, "io.example.App"), "yes")
        self.assertEqual(capture.permission_from_lookup(permissions, "other"), "no")
        self.assertIsNone(capture.permission_from_lookup(permissions, "missing"))
        self.assertIsNone(capture.permission_from_lookup({"empty": []}, "empty"))


class DiscardTests(unittest.TestCase):
    def test_removes_fresh_file_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            fresh = os.path.join(tmp, "fresh.png")
            old = os.path.join(tmp, "old.png")
            for path in (fresh, old):
                open(path, "wb").close()
            os.utime(old, (time.time() - 3600, time.time() - 3600))
            capture.discard_portal_file(fresh, time.time())
            capture.discard_portal_file(old, time.time())
            self.assertFalse(os.path.exists(fresh))
            self.assertTrue(os.path.exists(old))

    def test_missing_file_is_ignored(self):
        capture.discard_portal_file("/nonexistent/screencatch.png", time.time())


if __name__ == "__main__":
    unittest.main()
