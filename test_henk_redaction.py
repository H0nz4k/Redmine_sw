"""Synthetic privacy checks; never use production credentials as fixtures."""
import unittest

import henk_redaction as redact


class RedactionTests(unittest.TestCase):
    def test_obvious_credentials_and_link_targets_are_removed(self):
        source = (
            "Heslo: SyntetickeHeslo42; api_key=synthetic_key_123; "
            "REDMINE_API_KEY=syntheticPrefixedKey9 access_token='syntheticAccess9'; "
            "Authorization: Bearer abcdefghijklmnop. "
            "Odkaz https://example.invalid/file?token=synthetic_token a "
            "![soukromý-název](https://example.invalid/a.pdf) "
            "attachment:synteticka-priloha.pdf /attachments/12345/file.txt. "
            "Text závady zůstává dostupný."
        )
        result = redact.text(source)
        for value in ("SyntetickeHeslo42", "synthetic_key_123", "syntheticPrefixedKey9", "syntheticAccess9", "abcdefghijklmnop",
                      "synthetic_token", "example.invalid", "soukromý-název",
                      "synteticka-priloha.pdf", "/attachments/12345"):
            self.assertNotIn(value, result)
        self.assertIn("Text závady zůstává dostupný", result)

    def test_private_keys_and_structured_credentials_removed(self):
        source = "-----BEGIN PRIVATE KEY-----\nSYNTHETIC_KEY_BYTES\n-----END PRIVATE KEY-----"
        self.assertNotIn("SYNTHETIC_KEY_BYTES", redact.text(source))
        self.assertNotIn("SYNTHETIC_KEY_BYTES", redact.text("-----BEGIN PRIVATE KEY-----\nSYNTHETIC_KEY_BYTES"))
        result = redact.detail({"property": "cf", "name": "api_token",
                                "old_value": "synthetic-old", "new_value": "synthetic-new"})
        self.assertEqual(result["old_value"], redact.REMOVED)
        self.assertEqual(result["new_value"], redact.REMOVED)

    def test_attachment_metadata_is_not_in_context(self):
        value = {"issue_id": 7, "issue_source_id": "issue:7", "snapshot_safe": True,
                 "subject_snapshot": "Test", "description_snapshot": "Problém.",
                 "status_snapshot": {"id": 1, "name": "Nový"},
                 "attachments": [{"filename": "NEPOSILAT.pdf"}],
                 "journals_through_cutoff": [{"source_id": "journal:7:9",
                     "created_on": "2026-11-13T14:00:00Z", "author": "Eva", "notes": "Test.",
                     "details": [{"property": "attachment", "name": "NEPOSILAT.pdf", "new_value": "123"},
                                 {"property": "attr", "name": "status_id", "old_value": "1", "new_value": "2"}]}]}
        result = redact.context(value)
        self.assertNotIn("NEPOSILAT", str(result))
        self.assertNotIn("attachments", result)
        self.assertEqual(len(result["journals_through_cutoff"][0]["details"]), 1)


if __name__ == "__main__":
    unittest.main()
