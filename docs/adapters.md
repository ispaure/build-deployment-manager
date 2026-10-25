# Adapter contract and ownership

Adapter API 1 returns immutable `Plan`/`Phase` data. Plans declare structured
commands, source identity, dependencies, timeouts, cleanup and owned artifacts.
The headless engine imports neither Qt nor project code. Projects retain their
own interpreters and commonUtils pins, suites, native builders, release gates,
source snapshot policy, app versions, destinations and storage policy.

The manager owns process lifecycle, locking, redaction, generic transports,
profile mechanics, artifact capture and retention mechanisms. Logistics keeps
`Scripts/build_retention.py` as the single policy owner. No alternate project
cache tree is introduced. Shared API documentation belongs in commonUtils.

An engine result records manager and commonUtils commit/dirty identity alongside
adapter-supplied source/toolchain identity. Native transport acceptance is
separate from portable subprocess tests. VM holds are never bypassed by setup.
