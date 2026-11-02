# HookReplay roadmap

First milestone: persistent POST capture, inspection, local replay and HTTP attempt recording.

Remaining work estimates are rough engineering estimates, not time already worked:

- Completed: replay attempt inspection, network-error records and migration of existing databases.
- Cancellation and recovery of interrupted attempts: 3-5 hours.
- JSON Schema contract checks with useful field-level diagnostics: 6-10 hours.
- Deterministic duplicate, delay and reordering scenarios: 8-12 hours.
- Completed: bounded response capture and exact baseline comparison with completeness checks.
- Completed: structured JSON differences and exact ignored-field pointers.
- Completed: versioned comparison profiles, validation and CLI reuse.
- Completed: bounded readable text diffs and persistent named baseline selection.
- Completed: portable JSON fixture export/import, version 1 format, byte preservation and validation.
- Completed: named fixture collections, bounded local fixture discovery and atomic bulk import.
- Local request/replay review UI and end-to-end tests: 10-16 hours.
- Documentation, concurrent capture testing and packaging: 5-8 hours.

Each issue must have observable acceptance criteria and tests for failure paths. Scope stays ordinary HTTP integration development using synthetic data. Public ingress, arbitrary remote replay, real customer payloads and production deployment are outside this prototype.

Completed follow-up: named fixture collections. See README for scope and remaining limitations.

Completed packaging slice: installable wheel and console entry point with isolated installation checks in CI. Public package publication and broader release automation remain future work.

Completed scoped milestone: atomic bulk fixture import. See README for exact semantics and remaining limitations.

Completed scoped follow-up: concurrent capture and storage failures. See README for acceptance scope and remaining limitations.

Completed scoped follow-up: local fixture discovery. See README for precise behavior and remaining work.

Completed scoped follow-up: portable collection export. See README for limitations and remaining work.
