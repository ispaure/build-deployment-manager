# Repository instructions

Work on the current branch unless isolation is necessary. Preserve unrelated edits.
The manager owns generic execution, registration, settings mechanics, workflows,
transports and retention mechanisms. Projects own adapters, suites, source snapshots,
release policy, destinations and storage policy. commonUtils owns shared APIs.
Use Python as a source root, never as an import namespace. Keep headless imports
free of Qt and project modules. Keep project interpreters and dependencies isolated.
Use the pinned real Python/commonUtils submodule; never discover sibling checkouts.

Documentation lives in the root docs wiki, starting at docs/docs.md.
User setup and workflows belong in docs/user/; architecture, adapter contracts
and validation belong in docs/development/. Each folder
has a same-named landing linking every child. Every page begins with an H1.
Raw evidence belongs under ignored test-results, not in public documentation.

Validate actual changed contracts; distinguish portable tests from native acceptance.
Keep credentials as protected references. Do not access held VMs, mutate personal
devices, publish, push or dispatch without explicit applicable authorization.
