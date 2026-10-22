import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hookreplay import Store, load_profile, save_profile


class ProfileTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / 'rules.json'

    def test_round_trip_and_overwrite_protection(self):
        expected = save_profile(self.path, True, ['/time', '/id', '/time'])
        self.assertEqual(load_profile(self.path), expected)
        self.assertEqual(expected['ignored'], ['/id', '/time'])
        with self.assertRaises(FileExistsError):
            save_profile(self.path)
        self.assertEqual(load_profile(self.path), expected)

    def test_invalid_profiles(self):
        valid = {'version': 1, 'mode': 'json', 'ignored': []}
        cases = [[], dict(valid, version=True), dict(valid, version=2),
                 dict(valid, mode='unknown'), dict(valid, ignored='/time'),
                 dict(valid, ignored=[42]), dict(valid, ignored=['/bad~2']),
                 dict(valid, mode='bytes', ignored=['/time']), dict(valid, extra=True)]
        for case in cases:
            self.path.write_text(json.dumps(case))
            with self.assertRaises(ValueError):
                load_profile(self.path)
        for raw in ['{bad', '{"version":1,"version":1,"mode":"bytes","ignored":[]}', ' ' * 16385]:
            self.path.write_text(raw)
            with self.assertRaises(ValueError):
                load_profile(self.path)

    def test_invalid_save_leaves_no_file(self):
        with self.assertRaises(ValueError):
            save_profile(self.path, False, ['/time'])
        self.assertFalse(self.path.exists())

    def test_cli_profile_and_comparison(self):
        db = str(self.root / 'events.sqlite')
        command = [sys.executable, str(Path(__file__).resolve().parents[1] / 'hookreplay.py'), '--db', db]
        result = subprocess.run(command + ['profile', str(self.path), '--json', '--ignore', '/time'],
                                capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['mode'], 'json')
        self.assertFalse(Path(db).exists())
        store = Store(db)
        event = store.capture({}, b'fixture')
        for body in [b'{"time":1}', b'{"time":2}']:
            store.record_attempt(event, 'http://127.0.0.1/', status=200,
                                 headers={}, body=body, complete=True)
        result = subprocess.run(command + ['compare', '1', '2', '--profile', str(self.path)],
                                capture_output=True, text=True, check=True)
        report = json.loads(result.stdout)
        self.assertTrue(report['match'])
        self.assertEqual(report['profile']['ignored'], ['/time'])
        result = subprocess.run(command + ['compare', '1', '2', '--profile', str(self.path), '--json'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('cannot be combined', json.loads(result.stderr)['error'])

    def test_bytes_profile_keeps_exact_comparison(self):
        save_profile(self.path)
        self.assertEqual(load_profile(self.path), {'version': 1, 'mode': 'bytes', 'ignored': []})
