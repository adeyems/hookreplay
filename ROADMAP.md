# HookReplay roadmap

First milestone: persistent POST capture, inspection, local replay and HTTP attempt recording.

Remaining work estimates are rough engineering estimates, not time already worked:

- Replay attempt inspection, network-error records and cancellation: 5-8 hours.
- JSON Schema contract checks with useful field-level diagnostics: 6-10 hours.
- Deterministic duplicate, delay and reordering scenarios: 8-12 hours.
- Response capture, bounded body diffs and baseline comparison: 6-10 hours.
- Named synthetic fixtures, portable export/import and schema versioning: 5-8 hours.
- Local request/replay review UI and end-to-end tests: 10-16 hours.
- Documentation, concurrent capture testing and packaging: 5-8 hours.

Each issue must have observable acceptance criteria and tests for failure paths. Scope stays ordinary HTTP integration development using synthetic data. Public ingress, arbitrary remote replay, real customer payloads and production deployment are outside this prototype.
