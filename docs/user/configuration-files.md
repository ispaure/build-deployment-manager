# Editing your manager configuration

Open **More → App settings → Open configuration folder**. The window opens the active registry’s `configuration` folder, including when you launched the manager with `--registry`. On macOS the default is `~/Library/Application Support/BuildDeploymentManager/configuration`. On Windows the parent is `%APPDATA%/BuildDeploymentManager`. On Linux it is `$XDG_CONFIG_HOME/BuildDeploymentManager`, with `~/.config` as the default base.

| File relative to the manager’s data directory | Contents and usual edit |
| --- | --- |
| `configuration/devices/ios.ini`, `android.ini` in the same folder | Shared device IDs and names. Edit these directly. |
| `configuration/projects/<name>/registration.json` | One registered checkout, its path, last choices and named presets. The `root` field distinguishes worktrees with the same name. |
| `configuration/projects/index.json` | Maps stable registration IDs to filenames and records the selected checkout. Add, Locate, Select and Remove maintain this index. |
| `configuration/shared-settings.json` | Named account references, project-to-account bindings, machine settings and any explicit import receipts. Connected accounts maintains the account sections. |
| `configuration/projects/<name>/profile.json` | Adapter settings for that checkout, when its adapter uses the supplied profile. Use Project settings for validated changes. |
| `appearance.json` | Manager text size. App settings maintains it. |
| `resources/test-workers.json` under the host's default Manager root | Per-platform and computer-wide test worker ceilings. App settings validates changes and reconciles idle resource slots. |

## Limit parallel test workers

Open **More → App settings**. **Test workers per platform** limits participating
test phases for the same platform across all runs. **Test workers on this computer**
limits their combined reservations across platforms and projects. Both settings
apply to the current computer, including runs using a separate `--registry`.

Start with four per platform and eight on a 16-core computer. Smaller hosts
default to half their logical CPU count, at least one, and reduce the platform
ceiling to fit. Choose up to eight per platform when an audited runner benefits
from a larger pool. For two platforms, four plus four can run together under an
eight-worker host ceiling; an eight-worker phase takes that whole budget and the
second waits. The progress view reports the resource wait.

Only project-approved tests use multiple workers. Serial host tests reserve one;
native tools, compiler threads and other applications retain their own resource
policies, so the test ceiling is not a limit on total CPU use. Keep headroom when
builds run at the same time. Save changed limits after participating tests finish,
then prepare a new plan. Retained plans with old limits are rejected before tests
launch. Use App settings rather than hand-editing resource capacity files.

## Add or rename a shared device

Open the file for the device’s platform. Under the single `[devices]` header, enter one exact, case-sensitive device ID and display name per line. For Logistics on Android, enter the hardware serial returned by `getprop ro.serialno`. UTF-8 labels may contain spaces or percent signs.

```ini
[devices]
LabPhone42 = Build lab phone
LabTablet84 = QA tablet
```

Save the file and click **Reload** in the device picker. A project with a mobile recipient field for that platform offers the catalog alongside its own saved devices. If both sources contain an ID, the picker shows one entry. A custom catalog name takes precedence. Choose the recipients separately in each checkout. Removing a catalog line can leave an existing preset, saved selection or project-supplied choice referencing that ID.

**Add ID** in the picker adds a recipient to the current selection. To make it available across projects, add it to the INI as well. A catalog entry records identity and a label. Connection aliases, signing policy, pairing, actual availability, and permission to install remain part of preparation and review.

### How Logistics reaches Android

The catalog stores the hardware serial and display name. Logistics first tries the configured connection (including a run-specific Android connection override), then the hardware serial for USB, then the previously saved connection when it differs. If none responds, it looks for paired wireless debugging services advertising that hardware serial through ADB mDNS and, on macOS, Bonjour. For a network endpoint it tries `adb connect`. It requires an online device with the selected hardware serial. A different serial stops the attempt.

Wireless debugging must already be enabled and paired with this host. When service discovery is unavailable, enter the known debugging endpoint in Logistics’ Android connection overrides, keyed by the hardware serial, for example `{"LabPhone42":"192.0.2.12:37001"}`. Use the debugging port shown by the device. A remembered label alone cannot pair a device. Other projects supply their own transport logic.

## Name a project folder

Each registered checkout has a unique local name and a matching folder inside `configuration/projects/`. **Add project** offers a registration name, and the CLI accepts `build-manager add /path/to/worktree --name "Logistics QA"`. Names are compared without regard to case. The first registration with a given descriptor name keeps the plain name during migration; other existing worktrees gain a checkout-derived suffix. Internal IDs, account bindings and the descriptor’s project identity are preserved. Removing a registration retains its folder. Choose another name if a retained folder occupies the name you want.

## Share a GitHub login between projects

Open **Connected accounts**, name a GitHub reference and choose the existing credential helper or the **name** of an environment variable. Save for the current project, switch projects, select that same named reference, and save. Each adapter must declare the account fields it accepts. Bindings use the descriptor’s project ID, so worktrees of the same project share the binding. Existing explicit adapter profile overrides retain their precedence.

For a hand edit, the following is an example of `shared-settings.json`. Merge the relevant entries into your existing file. Substitute the actual descriptor project IDs. Keep token values and credential-file contents in their protected stores.

```json
{
  "schema": 1,
  "values": {
    "accounts": {
      "team-github": {
        "provider": "github",
        "kind": "environment-name",
        "reference": "TEAM_GITHUB_TOKEN",
        "status": "configured; not verified"
      }
    },
    "projects": {
      "example.app": {"accounts": {"github": "team-github"}},
      "example.tools": {"accounts": {"github": "team-github"}}
    },
    "machines": {}
  }
}
```

## Hand edits, backup and recovery

Close manager windows before editing registration or settings JSON. Copy the file first, retain the schema and field types, and restart the manager afterward. Device lists in saved run overrides use the adapter’s text representation, for example `"devices.ios": "[\"ExampleID\"]"`. Use the picker or save a preset for changes to those values. Keep the registration ID stable when moving a checkout. Use **Locate** to check the descriptor identity at its new path.

The first read by this manager creates the configuration tree as one operation. It copies every registration and preset, keeps the selected registration, and seeds the device catalogs from recognizable recipients in existing choices and presets. An unavailable checkout can still be located later. Its choices survive even if its descriptor was unavailable for seeding.

Previous top-level `registry.json` and `settings.json` files, when present, are snapshots from before migration. Later edits belong in `configuration/`. Use one manager version per data directory. For backup, copy `configuration/` and retain any legacy `projects/` data with the manager closed. For rollback to the previous version, retain the new tree as a separate backup and use the original top-level files with the old version. Its view will be the pre-migration state. To recover from an invalid hand edit, restore the affected file from your backup. The earlier UUID-named registration files and checkout profiles remain as migration backups. The active files are in the named project folders. A missing active index or registration file is an error.
