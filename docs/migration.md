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
