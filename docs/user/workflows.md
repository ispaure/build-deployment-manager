# Workflows, review and recovery

Use this guide when a workflow pauses or does not finish as expected. A saved
preset restores choices; resuming a retained run reuses verified work from that
run. Preparing a new plan captures source and settings again.

## Choose the next action

| Recorded state | What it means | Next action |
| --- | --- | --- |
| Awaiting review | An eligible effect needs approval | Inspect the exact prepared files and destination, then continue if intended |
| Waiting to reconnect | A declared pre-install availability check cannot reach its selected device | Reconnect that device or stop; the wait can retry without reinstalling |
| Failed check | A required gate did not pass | Read its test/log evidence, fix the cause and prepare again for changed source |
| Unknown outcome | An external action may have completed | Reconcile its provider/device outcome before retrying |
| Missing or changed artifact | Retained bytes no longer match the recorded identity | Recover the exact output or prepare a new run |
| Cancelled | Some work may already have finished | Read per-step outcomes before deciding what to resume |

Keep the original result directory. A disconnected network does not prove an
upload failed, and cancellation does not undo completed deliveries.

## A plan is still preparing

Review plan prepares source and prerequisites before execution. Its phase and
elapsed time describe preparation only. **Cancel preparation** requests cleanup;
wait until it says cancelled before preparing again. Legacy adapters may have to
finish their request before cancellation completes. Changed choices or project
settings supersede a pending request, including any late error. Prepare a new
review for those choices. Failed preparation keeps the draft and its error details.

You can open **Project History** while waiting. Saved evidence opens separately;
**Current run** or **Back to current run** returns to the draft or active run.
Reading evidence never starts or resumes execution. Closing during preparation
requests cleanup and prevents the result from opening a late review.

## Request cancellation from another terminal

Use `python -m build_manager.cli cancel RUN --expect-identity PLAN_SHA --confirm`
(or `ManagerAPI.cancel_run`) to request cancellation of that exact live saved run.
The response is **requested**, not finished. Read `status RUN` until the original
controller finishes its owned cleanup. Completed deliveries are not undone;
uncertain external outcomes still require reconciliation before retrying.

Each fresh attempt has its own nonce and request file, so an old requester cannot
cancel a resumed run or overwrite its acknowledged cancellation request.
`--expect-attempt NONCE` additionally binds automation to an inspected attempt.
Only admitted controllers advertising this protocol accept requests: a controller
still waiting for workflow resources, a finished/crashed controller, and older SDK
controllers fail actionably. Use the original controller's Stop/interrupt while
waiting for admission. This command never signals arbitrary processes, takes the
controller's supervisor lock, or edits its result report.

## Waiting for a device

Adapters can declare a separate connection check before installation. A temporary
availability failure shows **Waiting to reconnect** and retries automatically
until the selected device returns or you stop the run. The wait releases its
worker and resources between checks, so independent testing, builds, delivery
review and other recipients continue. Stop cancels the wait.

Resume the retained run to reuse passed tests and verified packages. Connection
checks do not approve installation; each recipient still needs review of its exact
package and destination. A signing or identity mismatch stops explicitly. An
interrupted installation has an uncertain outcome and requires reconciliation
before another install; only pre-install availability checks retry automatically.

## Execution and review

A workflow extends an existing versioned plan: dependency-ordered phases declare
commands, output artifact types and effects. The default is sequential. Source,
settings, adapter and toolchain data are captured once. Passing tests never
approves an external effect. Required failed/skipped/unknown dependencies block it.

For a fresh GUI plan, **Start reviewed workflow** authorizes the selected Firebase
and TestFlight uploads and GitHub actions. Release delivery runs after its required
checks and package preparation pass, without a second approval dialog. GitHub
hosted test launches also use Start authorization, then supply their test results
to dependent work. Review shows this scope before
Start. Failed checks still block delivery, and uncertain upload outcomes still
require reconciliation before retry. Existing saved runs keep their original
approval requirements; inspect a fresh plan to use this behavior.

Other explicit per-step upload/deploy/publish effects pause after preparation. Review
exact source/settings, retained artifact checksums, actual embedded identities and
destinations before approving. Approval is session-only and scoped to the complete
plan and verified prerequisite outputs. A changed or missing original/captured
artifact invalidates approval. Legacy whole-plan external effects retain their
existing explicit confirmation requirement; old plans gain no new provider mapping.

Each run atomically records state transitions and saves its original plan, logs,
artifacts, timings and engine/dependency identity. Resume in the GUI or run
`python -m build_manager PLAN --output RESULT_DIRECTORY --resume`.
After reviewing an awaiting step, use `--resume --confirm --approve-step STEP`.
Passed work is reused after checksum verification; only unsuccessful harmless
steps retry. Manager/dependency or plan identity changes require a new inspection.

Use CLI `resume --no-retry-failed` to continue independently ready deliveries
while preserving failed checks and their blocked steps. Review and approve the
exact pending delivery identities as usual. Passed artifacts are still verified;
unknown effects still require reconciliation. The overall run remains failed
until its required checks pass. A normal resume retries unsuccessful harmless
checks when you are ready to address them.

Resuming after a workspace admission failure keeps that failure and its message
in the attempt history. Once the new attempt acquires its resources, the current
outcome no longer shows the old admission error. Original failed attempts and
uncertain external outcomes remain retained.

The [guided UI](guided-ui.md) offers Configure, Review, Run and results, and
project-owned History. Review and continue delivery opens the current retained
run directly with source/settings and verified artifact evidence in one approval
dialog. Step clocks, declared JUnit cases and failure details remain attached to
their original run. Active duration accumulates across resume attempts; time spent
waiting between attempts for human approval is excluded.

If the execution process crashes or exits without a verified result, Summary
identifies incomplete evidence and includes its startup error when available.
Logs retains captured output. Steps that never started remain queued; an
interrupted running action can have an unknown outcome. Inspect the original
run evidence before deciding what to do next.

## Diagnose a failure and copy details

A newly finished failed run, or a failed run opened from Project History, starts
on **Summary**. It identifies the affected step and shows the reported assertion,
exception or an error excerpt from its logs. A log excerpt is a clue, not a new
execution outcome. **View failing test**, **View logs** and **View blocking step**
open the relevant evidence. A blocked step did not execute; follow its prerequisite
to find the cause. Completed, blocked and uncertain deliveries stay separate.

Choose **Copy diagnostics…** beside the error, or beside a selected test's details.
Review the text, optionally turn off **Include log or traceback excerpt**, then
choose **Copy**. The message confirms that the visible preview was copied. Opening
or closing the preview does not change the clipboard. Paste it manually where
you want to share it; the manager sends nothing. A later run update cannot change
the preview's captured identity or text.

Sharing excludes raw commands, environment/settings dictionaries and destination
identities, and filters known credentials, protected references and private paths.
Review the preview: arbitrary unlabeled text cannot be guaranteed secret-free.
The report marks omitted or unavailable evidence. Saved runs say **Not recorded**
for a preset name that was never captured. Viewer versions are separate from the
original recorded engine revisions.

After **Remove bulky files**, structured reports and outcomes can remain while logs
or screenshots are missing. Logs identifies missing, empty, unreadable and truncated
evidence. Opening saved evidence or copying a report never regenerates files,
resumes work or approves an action. **Back to current run** returns to the preserved
draft or current result.

A preparation failure retains your choices and offers the same preview; no run
started. After an unexpected manager exit, the next launch can offer **Inspect
diagnostics…** for a recorded manager error. An unexpected-exit marker without a
traceback says the cause is unavailable. These reports describe the GUI, not the
outcome of a separate executor. Inspect run history independently. **Dismiss
diagnostic** removes only the selected manager report. If diagnostic storage is
full or unavailable, a notice explains that recording is unavailable and keeps
existing reports. Run records and holds are unchanged.

Workflow cards show small Windows, Linux, Apple, Android, GitHub and Docker icons
when their declared platform or execution location is known. A card can show both
the target platform and its execution service. Hover for the icon names; the same
context is available to screen readers. Icons describe the affected platform or
service. Passed cards have a green background; failed cards have a red background.
Running cards show a progress bar at the bottom, with completed/total subtasks
when a task count is available. A single running step shows activity without an
invented percentage. Waiting cards stay neutral; cards blocked by a failed
prerequisite are greyed out and remain available for inspection. Status text
also describes the outcome.

Workflow maps start in Horizontal orientation. Use the orientation selector to
choose Vertical or Best fit; your choice stays in effect as the view refreshes
or resizes. Fit keeps the selected orientation.

During a live or retained run, selecting a workflow card updates the persistent
side pane. Review plan and Progress & results keep the same card overview;
selection does not enter a nested card browser. Use the pane's step selection to
inspect state, waiting reasons, errors and captured context. Summary, Tests, Logs
and applicable Artifacts or Deliveries follow the selected scope. View problems selects the
failing step and its reported problem. See the [guided UI](guided-ui.md) for the
available evidence controls.

Running cards and details use the same elapsed clock. Completed steps keep their
measured durations; skipped steps without measured runtime show Not started.
Main cards show Total step time (may overlap), which differs from active run time
and reported individual test time. Progress updates preserve graph navigation and
evidence text selection and scroll position.

Interrupted harmless work is retryable. A running/failed/timeout external effect
has an unknown outcome until its provider reconciles the recorded operation.
The recovery API accepts a project reconciler that returns a verified receipt or
confirms no effect occurred. Unknown effects and their consumers stay frozen;
Continue independent steps can run other eligible branches with their ordinary
artifact reviews. It never retries an unknown action or marks it passed. If only
uncertain actions and their blocked consumers remain, the GUI reports that
reconciliation is required instead of offering an empty continuation review.
Each destination retains its own outcome even if another branch fails or the
workflow is cancelled.

Application close offers cancellation and waits for owned cleanup. Continuing
execution after GUI shutdown is not implemented. Process IDs alone never authorize
termination. Captured outputs, original prepared artifact directories, workspace
and declared snapshot resources receive durable seven-day holds while awaiting
review/reconciliation. Active runs additionally hold OS leases. Terminal completion
releases only that run's holds. Expired/missing artifacts stop continuation clearly.
Existing .keep pins remain untouched. Project retention policy remains authoritative.
The cleanup inventory shows workflow hold expiry separately from `.keep` pins.
Protected trees can exceed a project's soft storage budget; awaiting review and
unknown outcomes retain their outputs even when no build process is running.

## Manage build storage

Open **More → Manage build storage…**. The selected checkout and scan status
appear first. The overview then shows estimates for project-declared build
storage and saved evidence from declared results folders as measurements become
available.

| Category | What it includes |
| --- | --- |
| **Builds and working files** | Build preparations, retained source snapshots, workspaces and other project-declared outputs. Removing them may require new preparation and can prevent retry or delivery using those files. |
| **Rebuildable caches** | Items the project adapter identifies as caches. Rebuilding them takes time. |
| **Saved runs and test results** | Local run records, reports, receipts, logs, screenshots, recordings and copied installers. Projects can declare older evidence folders as well. |

Use the category list to browse with the keyboard. Choose **Show space chart**
to compare measured amounts in the optional treemap. **Size on disk** estimates
allocated file bytes. A cached estimate can be stale during a refresh. A partial
estimate accounts for the known portion, and unknown sizes are marked. Shared
locations are counted once. The actual space reclaimed can differ on compressed,
cloned or hard-linked storage. Select an entry and choose **Item details…** to
inspect its path, protection and measurements in a scrollable view. In a narrow
window the chart replaces the category summary while the item list remains
visible; **Hide space chart** restores the category list. Choose **Refresh
storage** to update the inventory.
The **Available to review** column estimates removable build files or bulky
evidence; it excludes known protections. It is a starting point for review,
and the live checks can still keep an item.

### Review a cleanup

Select entries in **Builds and files** and choose **Review cleanup…**. Use
**Select available shown** to select eligible entries in the current view,
then review that selection before confirming. The preview shows the estimated
size and its freshness, what would be removed or kept, and any effect on retry
or delivery. Expand its details to see the selected locations and reasons for
excluded entries. **In use**, **Kept for a later run** and **Pinned to keep**
describe protections. Conflicting ownership can also block cleanup. Entries
marked **Available to review** are rechecked after confirmation. A changed entry
can require a fresh review.

### Clear local test evidence

In **Saved runs and test results**, select entries and open the preview for the
cleanup you want.

- **Remove bulky files…** removes raw logs, screenshots, recordings and copied
  installers from selected runs and removes selected loose evidence files. It
  keeps the run records, structured test reports and delivery receipts.
- **Delete entire runs…** removes selected runs from local history, including
  their records, reports and receipts. Use this when you no longer need that
  history.

Active runs, runs held for review or continuation, pinned evidence and unresolved
delivery outcomes are protected.

### Stop a scan or cleanup

Use **Stop** to cancel a scan. During cleanup, **Stop** lets the current deletion
finish and skips entries that have yet to start. If you choose **Close** while an
entry is being removed, the dialog waits for that deletion. Review the outcome
for the items that were removed, skipped or failed.
An incomplete removal may have removed some files. The refreshed inventory
shows what remains before another review.

### Retire workflows or adopt disposable storage

In **Advanced**, select superseded workflows and choose **Retire selected
workflows…**. Retirement releases their storage holds and permanently disables
continuation. Their original outcomes, logs and receipts stay in history. Check
the provider before preparing a replacement for an unknown delivery outcome.
Other workflows' holds and explicit `.keep` pins still apply. Review newly
eligible outputs in **Builds and files** if you want to remove them.

Projects that support adoption offer it in **Advanced**. Adopt only a location
the project can treat as disposable build or QA storage. Adoption puts the
specified location under the project's cleanup and automatic retention policy.

## Remote-controller cleanup grace

A VM controller can declare up to 300 seconds of bounded cooperative shutdown
before the local process group is forcibly retired. This gives it time to stop
its owned guest work, collect evidence and clean up remote files. The default is
still one second; existing plans retain that default when the field is absent.
This grace does not extend a test's execution timeout or authorize unrelated guest
operations. Windows child processes remain owned by their process job.

## Hosted test launches

`dispatch` identifies a remote workflow launch separately from publication,
upload or deployment. Fresh GUI plans authorize GitHub launches through Start;
older saved plans retain separate approval. It uses the same persisted intent and
unknown-outcome reconciliation as other external actions. A checks-only plan can
therefore run hosted tests without selecting a release destination or identifier.
Integrated plans bind dispatch steps to their selected platform and required gates.
For saved plans that still require approval, the UI labels their continuation
“Review and start GitHub checks”. Preparing or viewing a plan never starts a
dispatch; Start authorizes a fresh plan's selected GitHub actions.
