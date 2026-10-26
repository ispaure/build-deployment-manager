# Historical data and migration

Schema 1 plans and results remain readable without in-place rewriting. An old
plan remains trusted executable input; loading it never implies permission to
publish. Existing Logistics profiles, credential references, build counters,
prepared artifacts, result history and storage locations retain their owner.
The external engine is installed explicitly into each project tooling environment.
No leftover local engine is used as fallback.

Unsupported future schemas stop before execution. Preserve original files during
any explicit migration and validate the new settings before changing authority.
Prepared artifacts retain their captured identity when profiles change.

## Private settings layers

Shared account references, machine settings and per-project profiles have separate
namespaces in the private settings store. A field declares whether account or
machine defaults may supply it. Precedence is tracked defaults, selected account,
selected machine, project profile, documented environment variable, run override.
Guarded identities cannot be overridden. Effective values carry their origin.
Accounts cannot supply project destinations; authentication and signing remain
separate. Reference availability does not establish provider publish permission.

The GUI Accounts dialog stores protected file/helper/environment-name references,
never key/token contents. Project adapters declare allowed account field mappings.
Logistics maps shared TestFlight account JSON references and GitHub reference/kind
pairs; Blue Hole maps GitHub reference/kind pairs. Destinations remain project-owned.
Firebase CLI and existing Git credential-helper behavior remain project-owned.

Explicit legacy import validates and records a checksum before publishing private
settings. Repeating an unchanged import is idempotent; changed legacy input stops
for authority resolution. The original remains untouched and authoritative until
explicitly selected otherwise. Failed validation leaves it usable. No automatic
migration of the owner's live credentials or counters occurs. Logistics plans
capture effective settings and a private per-run profile; later settings edits
cannot relabel or redirect that plan's prepared artifacts.
