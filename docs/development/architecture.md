# Architecture and terms

Read this page before following an adapter request through the code. You need
basic Python and Git knowledge; mobile SDK and release-provider knowledge can wait
until you work on those integrations.

## How the three projects fit together

| Owner | Responsibility | Example |
| --- | --- | --- |
| Build Deployment Manager | Generic planning interfaces, process supervision, resource limits, review, history, transport and retention mechanics | Stop a child process and record its result |
| A project such as Logistics | Adapter, source snapshots, test suites, build commands, release gates, recipients and storage policy | Decide which iOS tests a TestFlight build requires |
| commonUtils | Reusable APIs used by the manager and applications | Atomic file publication, bounded streams and process helpers |

A transport performs an operation against a service or host. Project policy
chooses when that operation is allowed and what its destination means. For example,
a generic HTTP client cannot decide that a particular build is ready for testers.

Each checkout uses its own interpreter and pinned dependencies. The manager uses
its real `Python/commonUtils` submodule. A consumer may have a different pin.
Changing one checkout does not update the others. Keep `Python/` on the import
path as a source root: import `build_manager`, never `Python.build_manager`.

## Terms you will meet

| Term | Meaning |
| --- | --- |
| Registration | A trusted checkout known to this manager; two checkouts have separate registrations |
| Descriptor | The project's `build-project.json`, declaring its identity, interpreter, bridge and capabilities |
| Adapter | Project code that turns selected work and settings into a plan |
| Bridge | The subprocess boundary carrying structured JSON between manager and project interpreter |
| Plan | Captured source/settings and the exact commands, dependencies, outputs and effects to execute |
| Phase or step | One scheduled command in a plan; the code calls it a Phase and the UI generally calls it a step |
| Journey | A combined plan with explicit platform, execution-host and destination relationships |
| Backend | The declared execution choice, such as Local or GitHub; it is separate from the target platform |
| Gate | A prerequisite whose recorded success is required before dependent work can proceed |
| Artifact | A declared output retained with its identity, such as a report or signed package |
| Receipt | Evidence of an external operation's outcome, supplied and interpreted by its integration |
| Preset | Saved choices used to prepare a fresh plan; it does not contain approval |
| Lease, hold and pin | Protections against deleting in-use or retained outputs; see [recovery](../user/workflows.md) |

## Follow a validation run

1. `registry.py` reads the descriptor and resolves the registered checkout.
   Adding a checkout authorizes adapter execution; descriptor inspection alone
   does not run project code.
2. `bridge.py` asks the project's declared interpreter to prepare work. The project
   may capture source files during preparation. It returns Plan/Phase data; it
   does not get imported into the manager's process.
3. `models.py` validates the plan. The UI or CLI presents exact source, commands,
   effects and destinations. An editable workflow preview is only a proposal;
   preparation resolves the executable plan.
4. `executor.py` schedules eligible commands. Dependencies determine ordering;
   resource declarations and locks prevent incompatible work from overlapping.
   Declared cleanup retires owned work even after failure or cancellation.
5. `history.py` and `workflows.py` retain the plan, logs, artifacts and outcomes.
   Resume checks recorded identities before reusing work. An unknown external
   outcome needs reconciliation; it is not an ordinary failed test to retry.

The GUI and [automation API](automation-api.md) use the same engine. Qt belongs in
presentation modules. Headless modules must not import Qt or project modules.
The [developer guide](development.md#run-a-harmless-plan-before-changing-an-adapter)
has a complete disposable example of steps 3–5.

## Review and UI ownership

`configuration_ui.py` collects choices; `review_ui.py` presents a prepared plan;
`run_ui.py` coordinates progress and evidence. Review plan and Progress & results
use `ReviewPlanView` with `nested_navigation=False`. Selecting a workflow card
updates a persistent side pane without entering another card browser.

The nested browser in `grouped_workflow_ui.py` and its grouping/map support are
intentionally retained for a separate UX review. Their presence is not a reason
to reconnect or remove them during routine maintenance.

Starting a fresh GUI plan authorizes its selected Firebase/TestFlight uploads and
GitHub actions. Other declared effects can require a later artifact review.
Saved plans and CLI execution retain their declared approval requirements. Always
inspect the actual plan; do not infer permission from a provider name alone.
See [execution and review](../user/workflows.md#execution-and-review).

## Where to go next

- [Adapter contract](adapters.md): descriptor, bridge actions and project boundaries.
- [Journey contract](journey-contract.md): combined validation and delivery data.
- [Scheduling](scheduling.md): dependency edges, capacity and cleanup ownership.
- [Test organization](test-organization.md): suites and case evidence.
- [Validation scope](validation.md): dated acceptance and platform limitations.

[Developer guide](development.md)
