# Configuration storage assessment

## What made the old layout difficult to use

The manager already separated account references from project destinations and passed a checkout-specific profile path to each isolated adapter. Its main readability problem was the registration store. One UUID-keyed JSON map held checkout metadata, last-run inputs and named presets for every registration. Even a change to one selected device rewrote the whole map. Remembered recipients were embedded in adapter input strings. Finding all known phones required interpreting multiple sets of choices, while the adapter could have additional saved metadata of its own.

The former shared settings store already had named accounts and explicit per-project selections. Moving every credential reference out of adapter profiles automatically would change which worktrees or projects could use it. Existing profiles can also contain signing and provisioning paths alongside tool locations. Those fields have different ownership and precedence even though they all look like paths on disk.

## Ownership and format decisions

| Scope | Storage decision | Reason |
| --- | --- | --- |
| Device identity | One INI per mobile platform under `configuration/devices` | A person can add an exact ID and label on one line. Identity is reusable across checkouts. Selecting or approving a recipient is scoped to a run. |
| Registration | One uniquely named folder containing the registration and adapter profile, plus a small index | Names help people find a checkout. Stable IDs distinguish duplicate project names and preserve profile and history associations after relocation. JSON preserves nested presets, lists, booleans and numbers. |
| Account references | One typed JSON settings file with named references and explicit bindings by project ID | Two projects can choose the same account while retaining separate repositories and distribution targets. Raw credentials stay in credential helpers, protected files or environment variables. |
| Checkout configuration | Keep the adapter profile schema and copy its bytes into the named folder | The adapter owns validation, field precedence and migration. Interpreter selection belongs to the descriptor and remains project-specific. |
| Machine configuration | Retain existing machine settings and provider configuration | Generic hosts can be shared where a provider defines a contract. Executable paths, environments, signing identities and project VM policies require an explicit consumer before promoting them to shared defaults. |
| Build and operational state | Keep results, locks, evidence, retention data and source snapshots in their existing locations | These have independent lifetimes and may be active or governed by project retention policies. Moving them with editable preferences would couple backup and cleanup to ongoing executions. |

## Persistence and integration

Initial settings conversion stages the configuration tree under both writer locks. Registration conversion then stages a named projects tree containing its own index, registrations and copies of the checkout-specific profiles under the registry lock. A directory rename publishes it. Conversion reads descriptor metadata for device-field discovery and never imports an adapter. If a checkout is unavailable or has a changed identity, its registration and raw choices are still copied. The new tree is authoritative once published. A later read does not reimport an older snapshot.

Registry operations lock writers and atomically replace individual files. Adding writes the checkout file before publishing index membership. Removing drops membership, allowing readers that already opened the prior index to finish. The detached checkout file and adapter profile are retained. Re-registering creates a new ID. Normal project selection changes only the index. A preset edit changes only the owning checkout file. Registration names are unique case-insensitively; the index retains stable internal IDs. An optional local name distinguishes new worktrees of one descriptor.

Shared device lookup uses a destination’s declared recipient field and a single recognized iOS or Android platform. It merges IDs with adapter choices at the bridge boundary. Device records carry no signing or deployment policy. Adapters continue to receive only the selected run inputs. Private profiles and saved presets keep their exact representations.

## Scope of future sharing

A shared host or SDK default would be useful when at least two adapters declare the same field semantics, type, precedence and host applicability. The existing settings resolver has machine-eligible fields, but a value in the machine map alone does not configure an adapter. Keep project interpreter paths, repository identities, store destinations and cleanup ownership explicit. For devices with transport aliases or different signing policies, the project still resolves the exact target during preparation. Promoting these requires a typed adapter contract beyond a device ID and label.

See the [hand-editing guide](../user/configuration-files.md) for the on-disk contract and recovery procedure.
