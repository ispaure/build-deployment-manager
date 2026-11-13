# Storage management

The headless `storage_inventory.py` and `storage_cleanup.py` modules support the
[Manage build storage workflow](../user/workflows.md#manage-build-storage).
They work without Qt or in-process project imports. The project bridge resolves
the registered checkout and invokes its adapter in the project interpreter.

## Scope and accounting

An inventory covers the selected registration. The sources are the adapter's
current `storage_inventory` rows and evidence entries from the descriptor's
`results` and optional `test_evidence` folders. Only explicit adapter cache
descriptions can classify an output as a rebuildable cache. All other adapter
outputs go in Builds and working files and retain their project descriptions.
Run holds refer to entries and contribute no allocation of their own. The
retirement history is a separate view of held and retired runs.

Normalize paths, merge exact aliases and keep their owners and references. For
nested entries, assign known child allocations to their categories and assign
the known remainder to the parent. Incomplete or inconsistent measurements
produce partial estimates. An unknown allocation stays unknown. A conflict in
ownership or protection is a reason to withhold a destructive action. An adapter
may allow a separately declared nested cache to be removed from a held parent.
The separate Available to review estimate uses non-overlapping eligible output
footprints and bulky evidence bytes. It excludes entire-run history deletion
and known protections, and never replaces a fresh cleanup preflight.

Inventory work uses commonUtils `DirectoryCache` at the existing
`directory_index_path()` location. Scope scans to current inventory paths,
reuse covered descendants and reject linked ancestor chains. Discover candidates
from ownership declarations before indexing. A cached snapshot is a stale
estimate while the worker revalidates and refreshes. Close readers after use and
invalidate affected scopes after mutation.

Size on disk reports estimated allocated file bytes. Track unknown allocation,
incompleteness and freshness separately from the byte count. Keep any adapter
size estimate distinct from indexed allocation. The keyboard-accessible list
and optional commonUtils treemap use the same disjoint category totals. A
bounded chart sample cannot supply the inventory total. Actual reclaimed space
depends on filesystem behavior, including compression, clones and hard links.

## Preview and deletion authority

A cleanup preview binds the selected project and inventory identities, intended
action and available filesystem version facts. The preview accounts for covered
descendants and aliases, identifies protected or ambiguous selections, and
explains what the action removes and preserves. Confirmation defaults to No.

After confirmation, a fresh preflight checks registration, scope, selected
entry identity and current protection before the manager delegates any eligible
entries to their owners.

- **Adapter storage** goes through the existing `delete_storage` group/name
  protocol. The project applies its ownership, locking, lease, pin and hold
  checks. API 1 has no preview-issued inode token in the adapter transaction.
  Fresh manager preflight and the adapter's live admission are separate checks.
  The existing direct API and CLI storage actions continue to use the adapter
  contract. The reviewed dialog has its own preview and preflight.
- **Evidence cleanup** goes through `test_storage.py`. It rechecks declaration,
  links, protection, applicable locks, record or file identity and reviewed size.
  Bulky-only cleanup preserves run records, structured reports and delivery
  receipts. Whole-run cleanup removes history records after bulky content.
- **Retirement** goes through `run_retirement.py`. It records that the run can
  no longer continue and releases only its holds. It preserves evidence and the
  original outcomes, including unknown deliveries.
- **Adoption** goes through the adapter's `enroll_storage` action and follows
  project policy.

The index and the chart supply measurements and presentation. The adapter and
evidence or retirement owners apply the live guards at the point of mutation.

## Request lifecycle

The dialog presents scope and loading first. Inventory, index work and preflight
run off the Qt thread. Results belong to a request generation so that a stale
result or error cannot overwrite the current view. Read cancellation is
cooperative. During deletion, cancellation stops between selected entries and
allows the admitted operation to finish. Closing waits for that work to drain.
The cleanup result records completed, skipped and failed entries. Refresh
ownership and evidence after invalidating affected measurements and before
allowing further destructive actions.
