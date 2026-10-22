import http.server
import tempfile
import threading
import unittest
import json
import subprocess
import sys
from pathlib import Path

from hookreplay import MAX_RESPONSE, Store, compare, replay


class ResponseTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = Store(str(Path(self.temp.name) / 'test.sqlite'))
        self.event = self.store.capture({}, b'synthetic')
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                self.rfile.read(int(self.headers['Content-Length']))
                body = b'\x00\xffresponse'
                if self.path == '/changed':
                    body = b'changed'
                if self.path == '/large':
                    body = b'x' * (MAX_RESPONSE + 20)
                self.send_response(503 if self.path == '/status' else 200)
                self.send_header('Content-Type', 'text/plain' if self.path == '/header' else 'application/octet-stream')
                self.send_header('Content-Length', str(len(body) + (20 if self.path == '/short' else 0)))
                self.end_headers()
                self.wfile.write(body)
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever)
        self.thread.start()

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.temp.cleanup()

    def attempt(self, path):
        replay(self.store, self.event, f'http://127.0.0.1:{self.server.server_port}{path}')
        return self.store.attempts(self.event)[0]['id']

    def test_exact_match_and_independent_differences(self):
        baseline = self.attempt('/original')
        self.assertEqual(self.store.attempt(baseline)['response_body'], b'\x00\xffresponse')
        self.assertTrue(compare(self.store, baseline, self.attempt('/original'))['match'])
        for path, expected in [('/changed', 'response_body'), ('/status', 'status'), ('/header', 'response_headers')]:
            with self.subTest(path=path):
                result = compare(self.store, baseline, self.attempt(path))
                self.assertEqual(result['changed'], [expected])
                self.assertFalse(result['match'])

    def test_truncated_and_incomplete_responses_cannot_match(self):
        baseline = self.attempt('/original')
        for path in ['/large', '/short']:
            candidate = self.attempt(path)
            row = self.store.attempt(candidate)
            self.assertEqual(row['response_complete'], 0)
            self.assertLessEqual(len(row['response_body']), MAX_RESPONSE)
            with self.assertRaisesRegex(ValueError, 'complete'):
                compare(self.store, baseline, candidate)

    def test_legacy_and_different_events_rejected(self):
        baseline = self.attempt('/original')
        self.store.record_attempt(self.event, 'http://127.0.0.1/', status=200)
        legacy = self.store.attempts(self.event)[0]['id']
        with self.assertRaisesRegex(ValueError, 'complete'):
            compare(self.store, baseline, legacy)
        other = self.store.capture({}, b'other')
        self.store.record_attempt(other, 'http://127.0.0.1/', status=200)
        with self.assertRaisesRegex(ValueError, 'same captured event'):
            compare(self.store, baseline, self.store.attempts(other)[0]['id'])

    def test_cli_response_and_comparison_exit_codes(self):
        baseline = self.attempt('/original')
        prefix = [sys.executable, 'hookreplay.py', '--db', self.store.path]
        result = subprocess.run(prefix + ['response', str(baseline)], capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(result.stdout)['body_base64'], 'AP9yZXNwb25zZQ==')
        for path, code in [('/original', 0), ('/changed', 1)]:
            candidate = self.attempt(path)
            result = subprocess.run(prefix + ['compare', str(baseline), str(candidate)], capture_output=True, text=True)
            self.assertEqual(result.returncode, code)
            self.assertEqual(json.loads(result.stdout)['match'], code == 0)
