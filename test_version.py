"""Version and deployment fingerprint contract."""
import re
import unittest
from pathlib import Path
import redmine


class AppVersionTests(unittest.TestCase):
    def test_number_and_build_id_are_available(self):
        info = redmine.app_version()
        self.assertEqual(info['number'], (Path(redmine.__file__).resolve().parent / 'VERSION').read_text(encoding='utf-8').strip())
        self.assertRegex(info['build'], r'^[0-9a-f]{10}$')

    def test_map_changes_build_id(self):
        import tempfile
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'VERSION').write_text('test', encoding='utf-8')
            (root / 'mapa.html').write_text('first', encoding='utf-8')
            try:
                with patch.object(redmine, '__file__', str(root / 'redmine.py')):
                    redmine.app_version.cache_clear()
                    before = redmine.app_version()['build']
                    (root / 'mapa.html').write_text('second', encoding='utf-8')
                    redmine.app_version.cache_clear()
                    self.assertNotEqual(before, redmine.app_version()['build'])
            finally:
                redmine.app_version.cache_clear()

    def test_version_in_overview(self):
        # Does not connect to production Redmine.
        from unittest.mock import patch
        with patch.object(redmine, 'connect') as connect:
            db = connect.return_value.__enter__.return_value
            db.execute.return_value = []
            with patch.object(redmine, 'customers', return_value={'customers': []}):
                self.assertEqual(redmine.snapshot()['version'], redmine.app_version())


if __name__ == '__main__':
    unittest.main()
