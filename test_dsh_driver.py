import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dsh_driver import runtime_environment


class RuntimeEnvironmentTests(unittest.TestCase):
    """Moved from the removed bounded-delivery tests; dshrun still relies on this."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = Path(self.tmp.name) / 'desktop'
        self.home.mkdir()
        self.source = self.home / '.credentials.yaml'
        self.config = {'provider': 'deepseek-official', 'model': 'fixture'}

    def tearDown(self):
        self.tmp.cleanup()

    def test_bridges_only_official_key(self):
        self.source.write_text('version: 1\nrefs:\n  DEEPSEEK_API_KEY: sk-fixture\n  OTHER_KEY: hidden\nrecords: {}\n')
        self.source.chmod(0o600)
        with patch.dict(os.environ, {'DSH_HOME': str(self.home)}, clear=True):
            self.assertEqual(runtime_environment(self.config), {'DEEPSEEK_API_KEY': 'sk-fixture'})
            self.assertEqual(runtime_environment(self.config, True), {})
            self.assertEqual(runtime_environment({**self.config, 'provider': 'deepseek-account'}), {})
            with patch.dict(os.environ, {'DEEPSEEK_API_KEY': 'existing'}):
                self.assertEqual(runtime_environment(self.config), {})
        self.assertNotIn('sk-fixture', str(self.config))

    def test_rejects_unsafe_permissions_and_scalars(self):
        self.source.write_text('refs:\n  DEEPSEEK_API_KEY: sk-fixture\n')
        self.source.chmod(0o644)
        with patch.dict(os.environ, {'DSH_HOME': str(self.home)}, clear=True):
            with self.assertRaisesRegex(ValueError, 'owner-only'):
                runtime_environment(self.config)
            self.source.chmod(0o600)
            self.source.write_text('refs:\n  DEEPSEEK_API_KEY: |\n    secret\n')
            with self.assertRaisesRegex(ValueError, 'Unsupported'):
                runtime_environment(self.config)


if __name__ == '__main__':
    unittest.main()
