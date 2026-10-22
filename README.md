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

`attempts ID` shows the latest 100 attempts, newest first, with target, UTC time, HTTP status or network error. Network/protocol failures have a null status and a recorded error. HTTP errors retain their status. Replay exits with code 1 for network errors and non-2xx responses. Existing databases upgrade automatically while preserving records. Response bodies, interrupted-process recovery and cancellation are not yet supported; an HTTP status means response headers arrived, not that an application-side operation succeeded.

## Portable fixtures

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
