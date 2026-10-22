"""Local synthetic webhook capture and replay. Python 3.10+, no dependencies."""
import argparse
import base64
import difflib
import re
import http.client
import json
import sqlite3
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit

MAX_BODY = 1024 * 1024
SAFE_HEADERS = {'content-type', 'x-event-type'}
MAX_FIXTURE = 2 * MAX_BODY
MAX_RESPONSE = 64 * 1024


def export_fixture(store, event_id, path):
    event = store.get(event_id)
    fixture = {'version': 1, 'method': 'POST', 'headers': event['headers'],
               'body_base64': base64.b64encode(event['body']).decode('ascii')}
    # Exclusive creation protects existing fixtures from accidental overwrite.
    with open(path, 'x', encoding='utf-8') as output:
        json.dump(fixture, output, indent=2, sort_keys=True)
        output.write('\n')


def import_fixture(store, path):
    with open(path, 'rb') as source:
        raw = source.read(MAX_FIXTURE + 1)
    if len(raw) > MAX_FIXTURE:
        raise ValueError('Fixture exceeds 2 MiB')
    fixture = json.loads(raw)
    if not isinstance(fixture, dict) or set(fixture) != {'version', 'method', 'headers', 'body_base64'}:
        raise ValueError('Fixture must contain version, method, headers and body_base64 only')
    if type(fixture['version']) is not int or fixture['version'] != 1:
        raise ValueError('Unsupported fixture version; expected 1')
    if fixture['method'] != 'POST':
        raise ValueError('Only POST fixtures are supported')
    headers = fixture['headers']
    if not isinstance(headers, dict):
        raise ValueError('Fixture headers must be an object')
    for name, value in headers.items():
        if name not in SAFE_HEADERS or not isinstance(value, str):
            raise ValueError('Only lowercase content-type and x-event-type string headers are supported')
        if any(ord(char) < 32 or ord(char) == 127 or ord(char) > 255 for char in value):
            raise ValueError('Header values must be HTTP-compatible text without control characters')
    if not isinstance(fixture['body_base64'], str):
        raise ValueError('body_base64 must be a string')
    body = base64.b64decode(fixture['body_base64'], validate=True)
    if len(body) > MAX_BODY:
        raise ValueError('Decoded fixture body exceeds 1 MiB')
    return store.capture(headers, body)


class Store:
    def __init__(self, path):
        self.path = path
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, created TEXT, headers TEXT, body BLOB)')
            conn.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, event_id INTEGER, created TEXT, target TEXT, status INTEGER)')
            conn.execute('CREATE TABLE IF NOT EXISTS baselines (name TEXT PRIMARY KEY, attempt_id INTEGER NOT NULL)')
            columns = {row[1] for row in conn.execute('PRAGMA table_info(attempts)')}
            if 'error' not in columns:
                conn.execute('ALTER TABLE attempts ADD COLUMN error TEXT')
            for name, kind in [('response_headers', 'TEXT'), ('response_body', 'BLOB'),
                               ('response_complete', 'INTEGER')]:
                if name not in columns:
                    conn.execute(f'ALTER TABLE attempts ADD COLUMN {name} {kind}')

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path)
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def capture(self, headers, body):
        safe = {k.lower(): v for k, v in headers.items() if k.lower() in SAFE_HEADERS}
        with self.connect() as conn:
            result = conn.execute('INSERT INTO events(created,headers,body) VALUES (?,?,?)',
                                  (datetime.now(timezone.utc).isoformat(), json.dumps(safe), body))
            return result.lastrowid

    def get(self, event_id):
        with self.connect() as conn:
            row = conn.execute('SELECT id,created,headers,body FROM events WHERE id=?', (event_id,)).fetchone()
        if row is None:
            raise ValueError('Event not found')
        return {'id': row[0], 'created': row[1], 'headers': json.loads(row[2]), 'body': row[3]}

    def list(self):
        with self.connect() as conn:
            return conn.execute('SELECT id,created,length(body) FROM events ORDER BY id DESC LIMIT 100').fetchall()

    def record_attempt(self, event_id, target, status=None, error=None,
                       headers=None, body=None, complete=None):
        with self.connect() as conn:
            conn.execute('INSERT INTO attempts(event_id,created,target,status,error,response_headers,response_body,response_complete) VALUES (?,?,?,?,?,?,?,?)',
                         (event_id, datetime.now(timezone.utc).isoformat(), target, status, error,
                          json.dumps(headers) if headers is not None else None, body, complete))

    def attempt(self, attempt_id):
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute('SELECT * FROM attempts WHERE id=?', (attempt_id,)).fetchone()
        if row is None:
            raise ValueError('Attempt not found')
        result = dict(row)
        result['response_headers'] = json.loads(result['response_headers']) if result['response_headers'] is not None else None
        return result

    def attempts(self, event_id):
        self.get(event_id)
        with self.connect() as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute('SELECT id,event_id,created,target,status,error,response_complete,length(response_body) AS response_bytes FROM attempts WHERE event_id=? ORDER BY id DESC LIMIT 100',
                                (event_id,)).fetchall()
        return [dict(row) for row in rows]

    def name_baseline(self, name, attempt_id):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', name):
            raise ValueError('Baseline name must start with a letter and contain up to 64 letters, digits, underscores or hyphens')
        attempt = self.attempt(attempt_id)
        if attempt['response_complete'] != 1 or attempt['error']:
            raise ValueError('Baseline requires a complete response without network errors')
        try:
            with self.connect() as conn:
                conn.execute('INSERT INTO baselines VALUES (?,?)', (name, attempt_id))
        except sqlite3.IntegrityError as error:
            raise ValueError('Baseline name already exists; choose a new name') from error

    def resolve_baseline(self, reference):
        if str(reference).isdecimal():
            return int(reference)
        with self.connect() as conn:
            row = conn.execute('SELECT attempt_id FROM baselines WHERE name=?', (reference,)).fetchone()
        if row is None:
            raise ValueError('Named baseline not found')
        return row[0]

    def baselines(self):
        with self.connect() as conn:
            return [{'name': row[0], 'attempt_id': row[1]} for row in
                    conn.execute('SELECT name,attempt_id FROM baselines ORDER BY name')]


def readable_diff(store, baseline, candidate):
    texts = []
    for attempt_id in (baseline, candidate):
        row = store.attempt(attempt_id)
        if row['response_headers'].get('content-encoding', 'identity').lower() != 'identity':
            raise ValueError('Text diffs require uncompressed responses')
        try:
            text = row['response_body'].decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('Text diffs require UTF-8 bodies') from error
        # Escape terminal control characters, preserve line boundaries, show CR explicitly.
        text = ''.join(char if char == '\n' or char.isprintable() else repr(char)[1:-1] for char in text)
        lines = text.splitlines(keepends=True)
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n\\ No newline at end of file\n'
        if len(lines) > 2000:
            return 'Text diff omitted: response exceeds 2000 lines. Byte comparison remains exact.\n'
        texts.append(lines)
    output = []
    size = 0
    for line in difflib.unified_diff(*texts, fromfile=f'baseline-{baseline}', tofile=f'candidate-{candidate}'):
        size += len(line)
        if len(output) >= 200 or size > 16384:
            output.append('[Diff truncated; comparison used complete bodies.]\n')
            break
        output.append(line)
    return ''.join(output)


def json_differences(left, right, ignored):
    differences = []
    missing = object()

    def walk(a, b, path):
        if path in ignored:
            return
        if a is missing or b is missing:
            differences.append({'path': path, 'kind': 'added' if a is missing else 'removed'})
        elif isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(a.keys() | b.keys()):
                escaped = key.replace('~', '~0').replace('/', '~1')
                walk(a.get(key, missing), b.get(key, missing), path + '/' + escaped)
        elif isinstance(a, list) and isinstance(b, list):
            for index in range(max(len(a), len(b))):
                walk(a[index] if index < len(a) else missing,
                     b[index] if index < len(b) else missing, path + '/' + str(index))
        elif (isinstance(a, bool) != isinstance(b, bool) or
              (type(a) is not type(b) and not (type(a) in (int, float) and type(b) in (int, float)))):
            differences.append({'path': path, 'kind': 'type_changed'})
        elif a != b:
            differences.append({'path': path, 'kind': 'changed'})
    walk(left, right, '')
    return differences


def parse_json_body(body):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON object key')
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError(f'Invalid JSON constant: {value}')
    try:
        return json.loads(body, object_pairs_hook=unique_object, parse_constant=reject_constant,
                          parse_int=Decimal, parse_float=Decimal)
    except (ValueError, RecursionError) as error:
        raise ValueError(f'Response is not supported valid JSON: {error}') from error


def validate_rules(json_mode, ignored):
    if ignored and not json_mode:
        raise ValueError('--ignore requires --json')
    for pointer in ignored:
        if not isinstance(pointer, str) or not pointer.startswith('/'):
            raise ValueError('Ignored fields must use non-root JSON Pointers such as /metadata/time')
        for part in pointer.split('/')[1:]:
            index = 0
            while index < len(part):
                if part[index] == '~':
                    if index + 1 == len(part) or part[index + 1] not in '01':
                        raise ValueError('Invalid JSON Pointer escape; use ~0 or ~1')
                    index += 1
                index += 1


def save_profile(path, json_mode=False, ignored=()):
    validate_rules(json_mode, ignored)
    profile = {'version': 1, 'mode': 'json' if json_mode else 'bytes',
               'ignored': sorted(set(ignored))}
    encoded = json.dumps(profile, indent=2, sort_keys=True) + '\n'
    if len(encoded.encode('utf-8')) > 16384:
        raise ValueError('Profile exceeds 16 KiB')
    with open(path, 'x', encoding='utf-8') as output:
        output.write(encoded)
    return profile


def load_profile(path):
    with open(path, 'rb') as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError('Profile exceeds 16 KiB')

    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError('Duplicate profile key')
            obj[key] = value
        return obj
    try:
        profile = json.loads(raw, object_pairs_hook=unique)
    except RecursionError as error:
        raise ValueError('Profile nesting is too deep') from error
    if not isinstance(profile, dict) or set(profile) != {'version', 'mode', 'ignored'}:
        raise ValueError('Profile requires exactly version, mode and ignored')
    if type(profile['version']) is not int or profile['version'] != 1:
        raise ValueError('Unsupported profile version')
    if profile['mode'] not in ('json', 'bytes') or not isinstance(profile['ignored'], list):
        raise ValueError('Profile requires mode json/bytes and an ignored array')
    validate_rules(profile['mode'] == 'json', profile['ignored'])
    profile['ignored'] = sorted(set(profile['ignored']))
    return profile


def compare(store, baseline_id, candidate_id, json_mode=False, ignored=()):
    validate_rules(json_mode, ignored)
    baseline, candidate = store.attempt(baseline_id), store.attempt(candidate_id)
    if baseline['event_id'] != candidate['event_id']:
        raise ValueError('Comparison requires attempts for the same captured event')
    if any(row['response_complete'] != 1 or row['error'] for row in (baseline, candidate)):
        raise ValueError('Both attempts must have complete captured responses without network errors')
    changed = [name for name in ('status', 'response_headers', 'response_body') if baseline[name] != candidate[name]]
    details = {'mode': 'bytes', 'ignored': []}
    if json_mode:
        if any(row['response_headers'].get('content-encoding', 'identity').lower() != 'identity'
               for row in (baseline, candidate)):
            raise ValueError('JSON comparison requires uncompressed response bodies')
        left, right = (parse_json_body(row['response_body']) for row in (baseline, candidate))
        try:
            differences = json_differences(left, right, set(ignored))
        except RecursionError as error:
            raise ValueError('JSON nesting is too deep to compare') from error
        changed = [name for name in changed if name != 'response_body']
        if differences:
            changed.append('response_body')
        details = {'mode': 'json', 'ignored': sorted(set(ignored)),
                   'differences': differences[:100], 'difference_count': len(differences),
                   'differences_truncated': len(differences) > 100}
    return {'baseline': baseline_id, 'candidate': candidate_id, 'match': not changed, **details,
            'changed': changed, 'baseline_bytes': len(baseline['response_body']),
            'candidate_bytes': len(candidate['response_body'])}


def server(store, port=8081):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            if self.path != '/capture':
                self.send_error(404)
                return
            if self.headers.get('Transfer-Encoding'):
                self.send_error(400, 'Chunked encoding is unsupported')
                return
            try:
                length = int(self.headers.get('Content-Length', '-1'))
            except ValueError:
                length = -1
            if not 0 <= length <= MAX_BODY:
                self.send_error(413, 'A Content-Length between 0 and 1 MiB is required')
                return
            self.connection.settimeout(5)
            try:
                body = self.rfile.read(length)
            except TimeoutError:
                self.send_error(408)
                return
            if len(body) != length:
                self.send_error(400, 'Incomplete body')
                return
            event_id = store.capture(dict(self.headers), body)
            payload = json.dumps({'id': event_id}).encode()
            self.send_response(201)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
    return ThreadingHTTPServer(('127.0.0.1', port), Handler)


def replay(store, event_id, target):
    url = urlsplit(target)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password or url.fragment:
        raise ValueError('Replay target must be an HTTP URL on 127.0.0.1 without credentials or fragments')
    event = store.get(event_id)
    connection = http.client.HTTPConnection('127.0.0.1', url.port or 80, timeout=5)
    status, headers, body, complete = None, None, None, False
    try:
        path = url.path or '/'
        if url.query:
            path += '?' + url.query
        connection.request('POST', path, body=event['body'], headers=event['headers'])
        response = connection.getresponse()
        status = response.status
        headers = {key: response.getheader(key) for key in ('content-type', 'content-encoding') if response.getheader(key) is not None}
        body = response.read(MAX_RESPONSE + 1)
        complete = len(body) <= MAX_RESPONSE
        declared = response.getheader('content-length')
        if declared is not None and (not declared.isdecimal() or int(declared) != len(body)):
            complete = False
        store.record_attempt(event_id, target, status=status, headers=headers,
                             body=body[:MAX_RESPONSE], complete=complete)
        return status
    except (OSError, http.client.HTTPException) as error:
        if isinstance(error, http.client.IncompleteRead):
            body = error.partial[:MAX_RESPONSE]
        store.record_attempt(event_id, target, status=status, error=f'{type(error).__name__}: {error}',
                             headers=headers, body=body, complete=False)
        raise
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', default='hookreplay.sqlite')
    commands = parser.add_subparsers(dest='command', required=True)
    serve = commands.add_parser('serve')
    serve.add_argument('--port', type=int, default=8081)
    commands.add_parser('list')
    inspect = commands.add_parser('inspect')
    inspect.add_argument('id', type=int)
    attempts = commands.add_parser('attempts', help='Show the latest 100 replay attempts for an event')
    attempts.add_argument('id', type=int)
    detail = commands.add_parser('response', help='Inspect a captured response by attempt ID')
    detail.add_argument('id', type=int)
    diff = commands.add_parser('compare', help='Compare two complete responses for the same event')
    diff.add_argument('baseline', help='Attempt ID or saved baseline name')
    diff.add_argument('candidate', type=int)
    diff.add_argument('--json', action='store_true', dest='json_mode', help='Compare parsed JSON bodies')
    diff.add_argument('--ignore', action='append', default=[], metavar='POINTER', help='Ignore an exact JSON Pointer subtree; repeatable, requires --json')
    diff.add_argument('--profile', help='Load a saved profile; cannot combine with --json or --ignore')
    diff.add_argument('--text-diff', action='store_true', help='Print a bounded unified text diff; byte mode only')
    baseline = commands.add_parser('baseline', help='Save a name for a complete response attempt')
    baseline.add_argument('name')
    baseline.add_argument('attempt', type=int)
    commands.add_parser('baselines', help='List saved baseline names')
    profile = commands.add_parser('profile', help='Save reusable comparison rules to a new JSON file')
    profile.add_argument('file')
    profile.add_argument('--json', action='store_true', dest='json_mode')
    profile.add_argument('--ignore', action='append', default=[], metavar='POINTER')
    export = commands.add_parser('export', help='Export an event to a new portable JSON fixture')
    export.add_argument('id', type=int)
    export.add_argument('file')
    load = commands.add_parser('import', help='Validate a fixture and create a new event')
    load.add_argument('file')
    send = commands.add_parser('replay')
    send.add_argument('id', type=int)
    send.add_argument('target')
    args = parser.parse_args()
    if args.command == 'profile':
        result = save_profile(args.file, args.json_mode, args.ignore)
        print(json.dumps({'file': args.file, **result}))
        return
    profile_rules = None
    if args.command == 'compare' and args.profile:
        if args.json_mode or args.ignore:
            raise ValueError('--profile cannot be combined with --json or --ignore')
        profile_rules = load_profile(args.profile)
        args.json_mode = profile_rules['mode'] == 'json'
        args.ignore = profile_rules['ignored']
    store = Store(args.db)
    if args.command == 'serve':
        instance = server(store, args.port)
        print(f'Capturing synthetic requests at http://127.0.0.1:{instance.server_port}/capture', flush=True)
        try:
            instance.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            instance.server_close()
    elif args.command == 'list':
        print(json.dumps(store.list(), indent=2))
    elif args.command == 'inspect':
        event = store.get(args.id)
        event['body'] = event['body'].decode('utf-8', errors='replace')
        print(json.dumps(event, indent=2))
    elif args.command == 'attempts':
        print(json.dumps(store.attempts(args.id), indent=2))
    elif args.command == 'response':
        result = store.attempt(args.id)
        body = result.pop('response_body')
        result['body_base64'] = base64.b64encode(body).decode('ascii') if body is not None else None
        print(json.dumps(result, indent=2))
    elif args.command == 'compare':
        baseline_id = store.resolve_baseline(args.baseline)
        if args.text_diff and args.json_mode:
            raise ValueError('--text-diff requires byte comparison, not JSON mode')
        result = compare(store, baseline_id, args.candidate, args.json_mode, args.ignore)
        result['baseline_reference'] = args.baseline
        if profile_rules is not None:
            result['profile'] = {'file': args.profile, **profile_rules}
        if args.text_diff:
            difference = readable_diff(store, baseline_id, args.candidate)
            print(json.dumps(result, indent=2))
            print(difference, end='')
        else:
            print(json.dumps(result, indent=2))
        if not result['match']:
            raise SystemExit(1)
    elif args.command == 'baseline':
        store.name_baseline(args.name, args.attempt)
        print(json.dumps({'name': args.name, 'attempt_id': args.attempt}))
    elif args.command == 'baselines':
        print(json.dumps(store.baselines(), indent=2))
    elif args.command == 'export':
        export_fixture(store, args.id, args.file)
        print(json.dumps({'file': args.file}))
    elif args.command == 'import':
        print(json.dumps({'id': import_fixture(store, args.file)}))
    else:
        status = replay(store, args.id, args.target)
        print(json.dumps({'http_status': status}))
        if not 200 <= status < 300:
            raise SystemExit(1)


if __name__ == '__main__':
    try:
        main()
    except (ValueError, OSError, http.client.HTTPException, sqlite3.Error) as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        raise SystemExit(1)
