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

`--text-diff` uses exact byte comparison and prints the JSON result followed by a readable unified diff. It requires UTF-8, uncompressed responses and cannot be combined with JSON mode (including JSON profiles). Control characters and literal backslashes are escaped so they remain distinguishable. Missing final newlines are shown explicitly. The diff display is capped at 200 lines/16 KiB of UTF-8, including annotations and the truncation notice; bodies exceeding 2000 lines omit the diff. These display limits do not affect the full byte comparison or exit code. Omit `--text-diff` for machine-readable JSON-only output.

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

## Named fixture collections

Create an immutable, ordered event collection with `python3 hookreplay.py --db demo.sqlite collection checkout 2 1`. Discover collections with `collections`. Names use a letter followed by up to 63 letters, digits, underscores or hyphens. Collections reference 1–100 distinct existing event IDs in the same database; creation validates all members transactionally and never overwrites a name. No requests are sent. Portable collection export and atomic bulk fixture import are available as described below; collection-bundle import remains future work.

## Installable command

From this checkout, run `python3 -m pip install .` in a virtual environment. Then use `hookreplay --help` from any directory. Python 3.10+ is required; the package has no runtime Python dependencies. This installs locally and does not publish to PyPI. Run `python3 tools/check_install.py` to build a wheel and verify installation in a fresh virtual environment. Building requires setuptools from the configured package index.

## Atomic bulk fixture import

`hookreplay --db demo.sqlite import-many first.json second.json` validates 1–100 bounded fixture files, then imports them in argument order in one database transaction. Any invalid file or database insertion failure leaves no imported rows. The result contains ordered new IDs. Existing single-file import is unchanged. Duplicate input files intentionally create separate events. Validation can retain up to 100 MiB of decoded bodies in memory; use smaller batches when needed.

## Concurrent capture and storage failures

The listener backlog is explicitly 64 to accommodate small simultaneous local batches. The threaded capture endpoint is tested with 24 distinct binary payloads across eight concurrent clients, including reopening the database and checking unique IDs and byte preservation. SQLite storage errors return HTTP 503 with a generic message instead of closing the connection without a response. No successful capture is acknowledged before its transaction completes. This is correctness coverage, not a throughput guarantee; SQLite contention may still fail after its busy timeout. Clients must account for uncertain delivery if a connection drops after commit.

## Local fixture discovery

`hookreplay discover DIRECTORY` scans only that directory for regular `.json` files, validates the existing portable fixture format, and reports sorted filenames, validity and decoded body sizes. It does not open a database or import anything. Exit 1 means at least one invalid fixture. At most 100 JSON files and 1000 directory entries are accepted; excess fails rather than silently omitting results. Subdirectories and symlinks are skipped. This is intended for an ordinary local fixture folder, not an adversarial filesystem.

## Portable collection export

`hookreplay --db demo.sqlite export-collection NAME NEW.json` exports an ordered version-1 bundle with the collection name and inline version-1 fixtures. Database event IDs are deliberately omitted; binary bodies and selected headers are preserved. The total decoded body budget is 4 MiB and the encoded file budget is 8 MiB. Validation/encoding precedes exclusive file creation, so existing destinations are never overwritten. Storage failures may leave a partial new file. Bundle import and atomic publication remain future work; individual fixtures retain their existing import command.

## Deterministic replay scenarios

`hookreplay --db demo.sqlite replay-scenario PLAN.json http://127.0.0.1:8082/receive` runs an explicit version-1 plan: `{"version":1,"steps":[{"event_id":2,"delay_ms":0},{"event_id":1,"delay_ms":100},{"event_id":2,"delay_ms":0}]}`. Repeated IDs produce duplicates and array order defines reordering. All IDs and options validate before the first request; each delay is applied before its request, after the previous request finishes. Limits: 20 steps, 5000 ms per delay, 10000 ms total delay, 64 KiB plan. HTTP timeouts are additional and timing is not real-time guaranteed. Each completed/network-failed attempt uses normal persistence; network errors and non-2xx responses do not stop later steps. Ctrl-C returns completed results and an unreported count, but an interrupted request may already have reached the service. `http_success` covers HTTP status only, not response completeness or contract validity. Exit 1 indicates failed/stopped execution. Durable scenario resume and interrupted-attempt recovery remain unfinished.
