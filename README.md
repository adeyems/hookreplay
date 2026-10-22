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

## Tests

```sh
python3 -m unittest discover -s tests -v
```

See [ROADMAP.md](ROADMAP.md) for planned work. MIT licensed. This prototype has no claim of production readiness or programme acceptance.
