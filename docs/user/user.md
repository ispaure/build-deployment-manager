# Using the build manager

The manager helps you inspect and run a project's declared test, build and
delivery workflow. The project defines what those steps mean. Passing tests does
not automatically upload, install or publish anything.

## First run: choose the checkout before the operation

Complete [setup](setup.md) and open the platform launcher. Add the project
checkout. Adding it authorizes its adapter to load settings and prepare work
without a separate trust prompt. Project code runs in its declared interpreter. If you have
two checkouts, register them separately so history and settings remain distinct.

Use Add project at the top of the window. Choose or paste the project folder,
check its preview, then add it. The manager selects that project and explains the
next setup step. Project settings contains categories and search; App settings
controls the manager's appearance. Missing project environments have setup guidance.
The **?** at the upper right opens the manager's searchable Markdown documentation,
including this user guide and the developer guide. It stays available during runs.

For command-line registration, use the manager environment:

```sh
build-manager add /path/to/project
build-manager list
build-manager inspect REGISTRATION_ID
build-manager select REGISTRATION_ID
```

Replace `REGISTRATION_ID` with the ID printed by add/list. Use Locate after moving
a checkout. Removing a registration does not delete the
project or its results. Descriptor updates retain access; invalid descriptors and changed project identities are rejected.

## Run a focused check, then broaden it

In Choose work, select Validate and choose supported platforms. Projects with
combined workflow support offer several platform checkboxes; older projects show
one platform per run. Use Advanced operation for a project's suggested workflow
or specialist platform, operation and backend selection.
For an everyday code change, select a relevant project-declared suite if one is
available. The default uses the project's complete declared suite. Advanced
options include the source revision and focused pattern. A focused pass does
not replace the full gates required by a release workflow.

Choose Next: review plan, then read Review plan: source identity, settings, destination, ordered
steps and required dependencies. Inspection does not run the plan's commands,
although trusted project preparation may create its source snapshot. A change
to your selection invalidates the old plan. Start only after the
displayed checkout, source and host match your intention.

If a backend is unavailable, fix the stated prerequisite or explicitly choose
another declared backend. The manager does not silently substitute a hosted run.
Projects can allow working-tree tests while requiring committed release sources.
See [guided UI](guided-ui.md) for each control and [host requirements](hosts.md).

## Remember choices and save run presets

Each registered checkout remembers your last run choices automatically, including
checked device IDs, source revision, platforms, destinations, execution hosts,
run inputs, option toggles and build-number overrides. Project defaults remain
owned by the project; remembered inputs override them for your next run.
Saved device selections do not prove that a device is currently connected.

Use **Save preset…** to name the current choices within the selected project.
Choose a saved preset and **Load preset** to restore those choices, or
**Delete preset** to remove it. Saving with an existing name replaces that preset.
Presets belong to each registered checkout. Loading one invalidates the old plan;
review a new plan before starting. It never restores execution approvals.

The manager stores registrations, remembered choices and named presets in
`registry.json` under its private application configuration directory:

- macOS: `~/Library/Application Support/BuildDeploymentManager/`
- Windows: `%APPDATA%/BuildDeploymentManager/`
- Linux: `$XDG_CONFIG_HOME/BuildDeploymentManager/`, defaulting to `~/.config/BuildDeploymentManager/`

Shared account references and manager settings use `settings.json`; appearance
uses `appearance.json` in that directory. These files live outside your Git
checkout and are not committed with it. The CLI/GUI `--registry` option can select
a different directory; keep that directory outside source control as well.
Project settings storage is defined by the project's adapter. Credentials remain
protected references, and secret values are rejected from manager profiles.
On POSIX systems, manager registry files are written with owner-only permissions.

## Read outcomes, not just the progress bar

Steps shows all planned phases, their dependencies and durations. The progress
bar counts finished steps, including failed/skipped steps; it is not a success
percentage. Select a failed step for its error, log and retained artifacts.
Tests shows individual cases when the project declares a JUnit report. Missing
case rows can mean the adapter did not supply one; console output is not a
substitute for captured case evidence.

Cancel requests cooperative cancellation and owned cleanup. Closing during work
uses the same cancellation flow. Wait for the result before retrying; a timed-out
or interrupted external operation may already have reached its destination.
Keep the result folder when reporting a problem.

## Continue a prepared delivery

An integrated workflow may stop at Awaiting review after successful tests/builds.
Choose Review and continue delivery. Check the exact source/settings, verified
artifact identities and destination shown in that dialog. Declining leaves the
prepared run available. Approval applies to those outputs; changed or missing
files require a fresh preparation. Each external phase can require its own review.

An unknown upload/deployment outcome needs provider reconciliation before retry.

The manager verifies retained files in the background before opening delivery
review. The window remains responsive; Cancel operation also cancels this check.
Changing selections invalidates a late verification result. Approval is tied to
the verified prerequisites, which are checked again when execution resumes.

Do not start another upload merely because a network connection disappeared.
The [recovery guide](workflows.md) explains which passed steps can be reused
and why old approvals are not silently restored after restart.

## Return to an earlier run

Open Past runs, select the original run and choose View selected run for read-only
inspection. Compare its source and destination with today's selection. Resume
retained workflow continues that run separately; viewing history does not execute it.
Active time accumulates execution attempts and excludes time waiting between
attempts for human review. Individual phase durations remain attached to the run.

## Resolve common stops

| Message or symptom | Useful next step |
| --- | --- |
| Interpreter unavailable | Repair the selected project's environment; do not install project dependencies into the manager environment |
| Invalid descriptor or project identity changed | Correct the descriptor, or remove and add the intended checkout |
| Selection changed during preparation | Inspect a fresh plan; the old result cannot authorize the new selection |
| Another operation owns the workspace | Let its owner finish or cancel it through its manager; deleting a lock file is not ownership recovery |
| Artifact missing/changed | Restore the exact reviewed output if available, or prepare again; do not approve a replacement under the old identity |
| Remote outcome unknown | Use the project's provider reconciliation procedure before retrying |
| Tests passed but delivery blocked | Inspect required native/runtime/source gates and the pending review step |
| No individual tests shown | Inspect phase logs and ask whether the adapter declares JUnit evidence |

Storage cleanup operates only on project-declared owned groups. Review selected
entries; pins, leases and retained review holds can keep them protected. Application
data, signing keys and personal VMs are not disposable build outputs.

For support, include manager/project revisions, source selection, failed step,
platform and redacted error. Keep credentials and private document contents out
of shared reports. [Validation scope](../development/validation.md) distinguishes tested
native paths from unavailable platforms.

- [Documentation home](../docs.md)
- [Developer guide](../development/development.md)

## Further reading

- [CLI for automation and AI agents](cli.md)
- [Dedicated Fedora and Windows test machines](virtual-machines.md)
