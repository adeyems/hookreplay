import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hookreplay import Store, compare, readable_diff


class BaselineTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(str(Path(self.temp.name) / 'test.sqlite'))
        self.event = self.store.capture({}, b'fixture')

    def attempt(self, body, complete=True):
        self.store.record_attempt(self.event, 'http://127.0.0.1/', status=200,
                                  headers={}, body=body, complete=complete)
        return self.store.attempts(self.event)[0]['id']

    def test_names_persist_and_refuse_replacement(self):
        attempt = self.attempt(b'baseline')
        self.store.name_baseline('release-1', attempt)
        reopened = Store(self.store.path)
        self.assertEqual(reopened.resolve_baseline('release-1'), attempt)
        self.assertEqual(reopened.baselines(), [{'name': 'release-1', 'attempt_id': attempt}])
        for name in ['release-1', '123', '../test']:
            with self.assertRaises(ValueError):
                reopened.name_baseline(name, attempt)
        with self.assertRaises(ValueError):
            reopened.resolve_baseline('missing')
        with self.assertRaises(ValueError):
            self.store.name_baseline('incomplete', self.attempt(b'partial', False))

    def test_readable_changes_newlines_and_controls(self):
        a, b = self.attempt(b'hello\nold\n'), self.attempt(b'hello\nnew\n')
        diff = readable_diff(self.store, a, b)
        self.assertIn('-old\n+new\n', diff)
        c = self.attempt(b'hello\nold')
        self.assertIn('No newline at end of file', readable_diff(self.store, a, c))
        d = self.attempt(b'\x1b[31mtest\n')
        self.assertNotIn('\x1b', readable_diff(self.store, a, d))
        self.assertEqual(readable_diff(self.store, a, a), '')

    def test_binary_and_long_diff(self):
        a = self.attempt(b'a\n')
        with self.assertRaises(ValueError):
            readable_diff(self.store, a, self.attempt(b'\xff'))
        b = self.attempt(b'b\n' * 300)
        self.assertIn('Diff truncated', readable_diff(self.store, a, b))
        self.assertFalse(compare(self.store, a, b)['match'])

    def test_cli_named_baseline_and_diff(self):
        a, b = self.attempt(b'old\n'), self.attempt(b'new\n')
        prefix = [sys.executable, 'hookreplay.py', '--db', self.store.path]
        subprocess.run(prefix + ['baseline', 'stable', str(a)], check=True, capture_output=True)
        result = subprocess.run(prefix + ['compare', 'stable', str(b), '--text-diff'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('-old\n+new\n', result.stdout)
        result = subprocess.run(prefix + ['compare', 'stable', str(a)], capture_output=True, text=True, check=True)
        self.assertTrue(json.loads(result.stdout)['match'])
