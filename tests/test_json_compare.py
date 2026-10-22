import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from hookreplay import Store, compare


class JSONComparisonTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(str(Path(self.temp.name) / 'events.sqlite'))
        self.event = self.store.capture({}, b'fixture')

    def response(self, body, status=200):
        self.store.record_attempt(self.event, 'http://127.0.0.1/', status=status,
                                  headers={'content-type': 'application/json'},
                                  body=body.encode(), complete=True)
        return self.store.attempts(self.event)[0]['id']

    def test_format_order_and_numeric_equality(self):
        a = self.response('{"a":1,"b":[null,true]}')
        b = self.response('{ "b": [null, true], "a": 1.0 }')
        self.assertFalse(compare(self.store, a, b)['match'])
        self.assertTrue(compare(self.store, a, b, True)['match'])

    def test_nested_arrays_types_added_removed(self):
        a = self.response('{"items":[1,2],"old":null,"flag":true}')
        b = self.response('{"items":[1,3,4],"new":null,"flag":1}')
        result = compare(self.store, a, b, True)
        self.assertEqual({d['path']: d['kind'] for d in result['differences']},
                         {'/items/1': 'changed', '/items/2': 'added', '/old': 'removed',
                          '/new': 'added', '/flag': 'type_changed'})

    def test_ignore_subtrees_escaped_keys_and_array_positions(self):
        a = self.response('{"meta":{"time":1},"a/b":{"~key":1},"items":[1,2]}')
        b = self.response('{"meta":{"time":2},"a/b":{"~key":2},"items":[9,2]}')
        ignored = ['/meta', '/a~1b/~0key', '/items/0']
        self.assertTrue(compare(self.store, a, b, True, ignored)['match'])
        changed_status = self.response('{"meta":3}', status=503)
        self.assertIn('status', compare(self.store, a, changed_status, True, ignored)['changed'])

    def test_invalid_json_and_ignore_arguments(self):
        a = self.response('{}')
        for raw in ['bad', '{"a":1,"a":2}', 'NaN', 'Infinity']:
            with self.assertRaises(ValueError):
                compare(self.store, a, self.response(raw), True)
        for pointer in ['', 'meta', '/bad~2', '/bad~']:
            with self.assertRaises(ValueError):
                compare(self.store, a, a, True, [pointer])
        with self.assertRaises(ValueError):
            compare(self.store, a, a, False, ['/meta'])

    def test_large_numbers_do_not_collapse_to_infinity(self):
        a, b = self.response('1e999'), self.response('2e999')
        self.assertFalse(compare(self.store, a, b, True)['match'])

    def test_bounded_difference_report(self):
        a = self.response(json.dumps([0] * 120))
        b = self.response(json.dumps([1] * 120))
        result = compare(self.store, a, b, True)
        self.assertEqual(result['difference_count'], 120)
        self.assertEqual(len(result['differences']), 100)
        self.assertTrue(result['differences_truncated'])

    def test_cli_ignore_and_nonmatching_exit(self):
        a, b = self.response('{"time":1}'), self.response('{"time":2}')
        command = [sys.executable, 'hookreplay.py', '--db', self.store.path,
                   'compare', str(a), str(b), '--json']
        for extra, code in [([], 1), (['--ignore', '/time'], 0)]:
            result = subprocess.run(command + extra, capture_output=True, text=True)
            self.assertEqual(result.returncode, code)
            self.assertEqual(json.loads(result.stdout)['match'], code == 0)
