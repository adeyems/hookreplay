from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
import http.client
import json
import tempfile
import threading
import sqlite3
import socket
import subprocess
import sys
from contextlib import closing
import unittest
from pathlib import Path

from hookreplay import Store, replay, replay_scenario, server


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temp.name) / 'capture.sqlite')
        self.store = Store(self.path)
        self.http = server(self.store, 0)
        self.thread = threading.Thread(target=self.http.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()
        self.temp.cleanup()

    def post(self, body, path='/capture', headers=None):
        connection = http.client.HTTPConnection('127.0.0.1', self.http.server_port, timeout=10)
        try:
            connection.request('POST', path, body, headers or {})
            response = connection.getresponse()
            return response.status, response.read()
        finally:
            connection.close()

    def test_concurrent_capture_keeps_each_payload_and_unique_id(self):
        bodies = [f'synthetic-{i}'.encode() + b'\x00\xff' for i in range(24)]
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses = list(pool.map(self.post, bodies))
        ids = []
        reopened = Store(self.path)
        for body, (status, response) in zip(bodies, responses):
            self.assertEqual(status, 201)
            event_id = json.loads(response)['id']
            ids.append(event_id)
            self.assertEqual(reopened.get(event_id)['body'], body)
        self.assertEqual(len(set(ids)), 24)
        self.assertEqual(len(reopened.list()), 24)

    def test_storage_failure_is_explicit_and_server_recovers(self):
        with patch.object(self.store, 'capture', side_effect=sqlite3.OperationalError('private database detail')):
            status, body = self.post(b'synthetic')
        self.assertEqual(status, 503)
        self.assertNotIn(b'private database detail', body)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(self.post(b'next')[0], 201)

    def test_scenario_sends_exact_order_and_records_real_attempts(self):
        a=self.store.capture({},b'a')
        b=self.store.capture({},b'b')
        result=replay_scenario(self.store,f'http://127.0.0.1:{self.http.server_port}/capture',
            {'version':1,'steps':[{'event_id':i,'delay_ms':0} for i in [b,a,b]]},sleep=lambda _:None)
        self.assertTrue(result['http_success'])
        self.assertEqual([self.store.get(i)['body'] for i in [3,4,5]],[b'b',b'a',b'b'])
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT event_id,status FROM attempts ORDER BY id').fetchall(),[(b,201),(a,201),(b,201)])

    def test_capture_restart_inspect_replay_exact_bytes(self):
        body = b'{"event":"build.finished"}\n\x00\xff'
        status, result = self.post(body, headers={'Authorization': 'synthetic-secret', 'Content-Type': 'application/octet-stream'})
        self.assertEqual(status, 201)
        event_id = json.loads(result)['id']
        reopened = Store(self.path)
        self.assertEqual(reopened.get(event_id)['body'], body)
        self.assertNotIn('authorization', reopened.get(event_id)['headers'])
        self.assertEqual(replay(reopened, event_id, f'http://127.0.0.1:{self.http.server_port}/capture'), 201)
        self.assertEqual(reopened.get(2)['body'], body)
        with reopened.connect() as conn:
            self.assertEqual(conn.execute('SELECT event_id,status FROM attempts').fetchall(), [(event_id, 201)])

    def test_failed_http_response_is_recorded(self):
        event_id = self.store.capture({}, b'synthetic')
        self.assertEqual(replay(self.store, event_id, f'http://127.0.0.1:{self.http.server_port}/missing'), 404)
        with self.store.connect() as conn:
            self.assertEqual(conn.execute('SELECT status FROM attempts').fetchone(), (404,))

    def test_rejects_remote_targets_and_missing_events(self):
        for target in ['http://example.com/', 'http://127.0.0.1@example.com/', 'https://127.0.0.1/']:
            with self.assertRaises(ValueError):
                replay(self.store, 1, target)
        with self.assertRaisesRegex(ValueError, 'Event not found'):
            self.store.get(999)

    def test_body_limit_and_unknown_route(self):
        self.assertEqual(self.post(b'', headers={'Content-Length': '1048577'})[0], 413)
        self.assertEqual(self.post(b'', path='/unknown')[0], 404)
        self.assertEqual(self.store.list(), [])

    def test_network_failure_persists_and_cli_inspects_it(self):
        event_id = self.store.capture({}, b'synthetic')
        # Bound but not listening: refusal or timeout depending on the OS.
        with socket.socket() as reserved:
            reserved.bind(('127.0.0.1', 0))
            target = f'http://127.0.0.1:{reserved.getsockname()[1]}/receive'
            result = subprocess.run([sys.executable, 'hookreplay.py', '--db', self.path,
                                     'replay', str(event_id), target], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn('error', json.loads(result.stderr))
        result = subprocess.run([sys.executable, 'hookreplay.py', '--db', self.path,
                                 'attempts', str(event_id)], capture_output=True, text=True, check=True)
        attempts = json.loads(result.stdout)
        self.assertEqual(len(attempts), 1)
        self.assertIsNone(attempts[0]['status'])
        self.assertTrue(attempts[0]['error'].startswith(('ConnectionRefusedError:', 'TimeoutError:')))
        self.assertEqual(attempts[0]['target'], target)

    def test_attempt_filter_and_http_status(self):
        first = self.store.capture({}, b'first')
        second = self.store.capture({}, b'second')
        replay(self.store, first, f'http://127.0.0.1:{self.http.server_port}/missing')
        self.assertEqual(self.store.attempts(first)[0]['status'], 404)
        self.assertIsNone(self.store.attempts(first)[0]['error'])
        self.assertEqual(self.store.attempts(second), [])

    def test_upgrade_preserves_legacy_attempts(self):
        legacy = str(Path(self.temp.name) / 'legacy.sqlite')
        with closing(sqlite3.connect(legacy)) as conn, conn:
            conn.execute('CREATE TABLE attempts (id INTEGER PRIMARY KEY, event_id INTEGER, created TEXT, target TEXT, status INTEGER)')
            conn.execute("INSERT INTO attempts VALUES (1,1,'2026-10-22','http://127.0.0.1/',201)")
        migrated = Store(legacy)
        event_id = migrated.capture({}, b'fixture')
        self.assertEqual(Store(legacy).attempts(event_id)[0]['status'], 201)
        self.assertIsNone(migrated.attempts(event_id)[0]['error'])


if __name__ == '__main__':
    unittest.main()
