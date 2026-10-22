# HookReplay

A local command-line tool for capturing synthetic webhook requests, inspecting them and replaying their exact body bytes to a local development endpoint. For developers testing HTTP integrations. Python 3.10+ and SQLite; no third-party dependencies.

## Try it

```sh
python3 hookreplay.py serve
```

In another terminal:

```sh
curl -X POST http://127.0.0.1:8081/capture -H 'Content-Type: application/json' -d '{"event":"build.finished","build":42}'
python3 hookreplay.py list
python3 hookreplay.py inspect 1
python3 hookreplay.py replay 1 http://127.0.0.1:8081/capture
python3 hookreplay.py attempts 1
```

The example replay creates a second capture, demonstrating byte-preserving replay. Records persist in `hookreplay.sqlite`. Use `--db PATH` before the command to select another database.

## Current limits

POST capture only, 1 MiB maximum body, HTTP replay to literal 127.0.0.1 only, five-second network timeout, no automatic retries or redirects. Only Content-Type and X-Event-Type headers are retained. Bodies are stored verbatim: this is not a redaction system. Use synthetic payloads only. Request paths and query strings are not captured. The inspector displays text; binary bodies remain intact in storage and replay.

`attempts ID` shows the latest 100 attempts, newest first, with target, UTC time, HTTP status, network error, captured response size and completeness. Failures before receiving headers have a null status; later failures preserve the received status. Replay exits with code 1 for network errors and non-2xx responses. Existing databases upgrade automatically while preserving records. Interrupted-process recovery and cancellation are not yet supported.

## Response comparison

Replay the same event against your baseline and modified local endpoint, then use the attempt IDs from `attempts`:

```sh
python3 hookreplay.py response 1
python3 hookreplay.py compare 1 2
```

Each replay stores up to 64 KiB of raw response bytes, HTTP status, Content-Type and Content-Encoding. `response` outputs binary-safe base64. `compare BASELINE CANDIDATE` reports which of status, selected headers and exact body bytes changed, and both body sizes. Other headers (including Date and cookies) are excluded. Comparison exits 0 for a match and 1 for differences or invalid input; errors are JSON on stderr, comparison reports are JSON on stdout.

Both attempts must belong to the same event and have complete captured responses. Truncated, prematurely closed, failed or legacy uncaptured responses cannot be compared. Replay may return a 2xx status even when capture is incomplete: inspect `response_complete` or use `compare` as the regression gate. Any complete HTTP status can serve as a baseline, including expected 4xx/5xx responses. By default bodies are compared literally; opt into JSON mode below for structured comparisons. This verifies response equality, not application-side correctness. The five-second socket timeout applies to individual network operations, not the whole response duration.

## Structured JSON comparison

```sh
python3 hookreplay.py compare 1 2 --json
python3 hookreplay.py compare 1 2 --json --ignore /metadata/timestamp --ignore /requestId
```

JSON mode compares parsed bodies: whitespace and object-key order do not matter, numbers compare by value, and arrays compare by position. Booleans remain distinct from numbers. Differences identify JSON Pointer paths and kinds (`added`, `removed`, `changed`, `type_changed`), with up to 100 entries and a total count. Values are omitted from the report. An empty path denotes a difference at the document root.

`--ignore` skips an exact path and its entire subtree on either side, including additions or removals. It requires `--json`. Use `/items/0` for an array element, `~1` for a slash in a key and `~0` for a tilde. Wildcards and ignoring the document root are unsupported; unmatched paths have no effect. Ignore rules are listed in the report. Status and selected response headers are still compared.

Malformed JSON, duplicate keys, NaN/Infinity, excessive nesting and compressed response bodies are rejected. Capture completeness requirements still apply. Default comparison remains byte-exact. JSON mode does not persistently modify the captured response or baseline.

## Named baselines and readable text diffs

```sh
python3 hookreplay.py baseline stable 1
python3 hookreplay.py baselines
python3 hookreplay.py compare stable 2 --text-diff
python3 hookreplay.py compare stable 2 --profile comparison.json
```

Names persist in the selected SQLite database and identify one complete response attempt. Names start with a letter and contain up to 64 letters, digits, hyphens or underscores. Existing names cannot be replaced; use a new name for a revised baseline. Comparing still requires the same event and complete responses. Numeric attempt IDs remain supported.

`--text-diff` uses exact byte comparison and prints the JSON result followed by a readable unified diff. It requires UTF-8, uncompressed responses and cannot be combined with JSON mode (including JSON profiles). Control characters are escaped. Missing final newlines are shown explicitly. Display is capped at 200 diff lines/16 KiB; bodies exceeding 2000 lines omit the diff. These display limits do not affect the full byte comparison or exit code. Omit `--text-diff` for machine-readable JSON-only output.

## Reusable comparison rules

```sh
python3 hookreplay.py profile comparison.json --json --ignore /metadata/timestamp --ignore /requestId
python3 hookreplay.py compare 1 2 --profile comparison.json
```

Profiles are portable JSON files suitable for version control. Version 1 has exactly three fields: `version` (integer 1), `mode` (`json` or `bytes`), and `ignored` (an array of exact JSON Pointers). Creating a profile without flags saves byte-exact mode. Ignore paths require JSON mode, and duplicate paths are normalized. Creation refuses to overwrite an existing file and does not create a database.

`--profile` cannot be combined with `--json` or `--ignore`; edit the profile or choose inline flags. Reports include the profile path, version and effective settings. Baseline IDs stay on the command line, allowing the same rules to be used with different captured events. Invalid versions, duplicate or unknown keys, malformed rules and files over 16 KiB are rejected before comparison. Profiles do not suppress status/header changes or bypass completeness checks.

## Fixture export and import

```sh
python3 hookreplay.py export 1 build-finished.json
python3 hookreplay.py --db another.sqlite import build-finished.json
python3 hookreplay.py --db another.sqlite inspect 1
```

Export creates a new file and refuses to overwrite an existing one. Import validates the entire fixture before inserting a new event; repeat imports intentionally create separate events. The returned JSON contains the new event ID. No network request is made during import.

Version 1 fixtures contain exactly `version: 1`, `method: "POST"`, `headers`, and `body_base64`. Base64 preserves binary bytes; it is not encryption or redaction. Only lowercase `content-type` and `x-event-type` headers with HTTP-compatible values are accepted. Bodies are limited to 1 MiB and files to 2 MiB. Unknown versions, fields, invalid base64 and unsupported headers are rejected. Capture timestamps, database IDs, destinations and attempt history are deliberately not transported. Keep fixture filenames descriptive and use synthetic content.

## Verification

```sh
python3 -m unittest discover -s tests -v
```

See [ROADMAP.md](ROADMAP.md) for planned work. MIT licensed. This prototype has no claim of production readiness or programme acceptance.
