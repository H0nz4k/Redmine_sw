"""Offline checks for the bounded, read-only Henk/Redmine diagnostic."""
import unittest
import urllib.error
from unittest.mock import Mock

import diagnose_henk_redmine as diag


class DummyResponse:
    status = 200
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False


class DiagnosticTests(unittest.TestCase):
    def test_bounded_get_to_fixed_allowlist(self):
        opener = Mock()
        opener.open.return_value = DummyResponse()
        result = diag.collect(opener)
        self.assertEqual(len(result["checks"]), len(diag.PROBES))
        self.assertTrue(all(v["reachable"] for v in result["checks"].values()))
        self.assertEqual(opener.open.call_count, len(diag.PROBES))
        for call in opener.open.call_args_list:
            request = call.args[0]
            self.assertEqual(request.get_method(), "GET")
            self.assertIn(request.full_url, [url for _, url in diag.PROBES])
            self.assertIsNone(request.data)
            self.assertEqual(call.kwargs["timeout"], diag.TIMEOUT_SECONDS)
        self.assertNotIn("password", str(result).lower())
        self.assertNotIn("token", str(result).lower())

    def test_network_error_is_not_a_success(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.URLError("offline")
        result = diag.probe(diag.PROBES[0][1], opener)
        self.assertEqual(result["reachable"], False)
        self.assertIsNone(result["http_status"])

    def test_http_404_proves_server_only(self):
        opener = Mock()
        opener.open.side_effect = urllib.error.HTTPError(
            diag.PROBES[0][1], 404, "Not Found", None, None)
        result = diag.probe(diag.PROBES[0][1], opener)
        self.assertEqual(result["http_status"], 404)
        self.assertEqual(result["interpretation"], "http_route_not_ready_or_protected")

    def test_arbitrary_url_rejected_without_contact(self):
        opener = Mock()
        with self.assertRaisesRegex(ValueError, "allowlist"):
            diag.probe("http://evil.example.test/upload", opener)
        opener.open.assert_not_called()


if __name__ == "__main__":
    unittest.main()
