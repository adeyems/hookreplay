import base64
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hookreplay import MAX_BODY, Store, export_fixture, import_fixture


class FixtureTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = Store(str(self.root / 'events.sqlite'))
        self.file = self.root / 'event.json'

    def test_binary_round_trip_between_databases_via_cli(self):
        body = bytes(range(256)) + b'\n'
        event_id = self.store.capture({'Content-Type': 'application/octet-stream'}, body)
        subprocess.run([sys.executable, 'hookreplay.py', '--db', self.store.path,
                        'export', str(event_id), str(self.file)], check=True, capture_output=True)
        other = Store(str(self.root / 'other.sqlite'))
        result = subprocess.run([sys.executable, 'hookreplay.py', '--db', other.path,
                                 'import', str(self.file)], check=True, capture_output=True, text=True)
        event = other.get(json.loads(result.stdout)['id'])
        self.assertEqual(event['body'], body)
        self.assertEqual(event['headers'], {'content-type': 'application/octet-stream'})
        self.assertEqual(other.attempts(event['id']), [])

    def test_export_refuses_overwrite(self):
        event_id = self.store.capture({}, b'fixture')
        self.file.write_text('existing', encoding='utf-8')
        with self.assertRaises(FileExistsError):
            export_fixture(self.store, event_id, self.file)
        self.assertEqual(self.file.read_text(), 'existing')

    def test_rejects_invalid_fixture_without_inserting(self):
        valid = {'version': 1, 'method': 'POST', 'headers': {}, 'body_base64': ''}
        invalid = [[], dict(valid, version=True), dict(valid, version=2),
                   dict(valid, method='GET'), dict(valid, extra='unknown'),
                   dict(valid, headers={'authorization': 'synthetic'}),
                   dict(valid, headers={'content-type': 'text/plain\r\nX-Test: invalid'}),
                   dict(valid, headers={'x-event-type': 42}),
                   dict(valid, body_base64='%%%'), dict(valid, body_base64=42),
                   dict(valid, body_base64=base64.b64encode(b'x' * (MAX_BODY + 1)).decode())]
        for fixture in invalid:
            with self.subTest(fixture_type=type(fixture).__name__):
                self.file.write_text(json.dumps(fixture), encoding='utf-8')
                with self.assertRaises(ValueError):
                    import_fixture(self.store, self.file)
                self.assertEqual(self.store.list(), [])

    def test_empty_body_and_repeat_import_create_independent_events(self):
        event_id = self.store.capture({}, b'')
        export_fixture(self.store, event_id, self.file)
        first = import_fixture(self.store, self.file)
        second = import_fixture(self.store, self.file)
        self.assertNotEqual(first, second)
        self.assertEqual(self.store.get(second)['body'], b'')

    def test_malformed_and_oversized_files(self):
        for raw in [b'{bad', b'\xff', b' ' * (2 * MAX_BODY + 1)]:
            self.file.write_bytes(raw)
            with self.assertRaises(ValueError):
                import_fixture(self.store, self.file)
            self.assertEqual(self.store.list(), [])
