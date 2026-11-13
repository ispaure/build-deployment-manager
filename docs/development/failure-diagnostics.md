# Failure diagnosis and manual sharing

The results view is a read-only projection. It must not change scheduling,
approval, resume, recovery, delivery outcomes or retention. Both Review and
Progress keep the persistent side pane and `nested_navigation=False`; the dormant
nested browser remains unhooked.

## Presentation and evidence

`diagnostics.diagnose` uses recorded test failures, exit codes, reasons and
dependency relationships. A negative POSIX exit or explicit crash observation
supports process-crash wording; a generic nonzero exit does not prove a crash or
missing dependency. A diagnostic-looking log line is labeled as a hint. Actual
failed steps precede skipped descendants when opening a failure, and unknown
effects retain reconciliation guidance. Current and saved runs share this logic.

`RunView.complete` selects Summary only at the first failed completion/hydration.
Subsequent updates and saved-tab reactivation preserve reading. Summary's direct
actions select the relevant case, log or blocking prerequisite. Timing belongs
inside Tests. The Technical evidence disclosure retains the captured plan,
dependencies, command, step record, complete report and storage-maintenance data.
Logs contains actual output, not serialized reports.

Retained logs are constrained to a regular non-linked file below the declared run
directory. Read at most 256 KiB plus a sentinel, discarding a cut boundary line.
Missing, empty, unreadable and truncated evidence are distinct. Opening Logs
explicitly refreshes its retained preview; routine updates preserve selection and
scroll. Stored artifact identities do not imply the bytes still exist after cleanup.
No diagnosis action regenerates evidence or changes a retention hold.

## Sharing boundary

`format_diagnostics` enumerates fields rather than serializing a Plan or report.
It allows bounded project/preset/operation labels, run/step/case identities,
recorded status, explicit platform/execution labels, recorded engine revisions/API,
exit/exception information, prerequisite IDs, delivery counts and one excerpt.
Viewer Python/Qt versions are labeled separately. Existing saved runs have no
preset provenance; show Not recorded. Never read the current picker for a saved
run or add schema backfills to make this field appear known.

`redaction.ShareRedactor` adds sharing-only filtering around the existing manager
redaction owner. It filters known values, protected references, credential/key
blocks, sensitive assignments/options, private paths/identities, URLs, terminal
escapes and traceback source lines. Ordinary retained-log redaction is unchanged.
Each field begins a fresh stream; each excerpt processes complete ordered lines
before selection or truncation. Do not share a tail whose key-block context is
unknown. Unlabeled historical text may contain values no longer known locally;
filtering is best effort, not a proof of secrecy. Preview and omit-excerpt controls
are part of this boundary.

Labels are bounded to 160 characters (preset 100), messages to 2 KiB, failed case
identifiers to 20 and excerpts to 80 complete lines/8 KiB. Complete reports are at
most 16 KiB UTF-8, with explicit omissions. Output never includes full argv, cwd,
environment, settings, adapter/source dictionaries or destination account/device
identities. Structured source evidence remains accessible locally.

`DiagnosticPreview` receives an immutable snapshot factory. A worker reads/formats
the bounded evidence without retaining widgets. A parented timer accepts results
only while the dialog is live; close retires delivery even if a read is completing.
Both excerpt variants are frozen before Copy is enabled. Only the explicit Copy
action writes exactly the displayed text through an injectable clipboard boundary.
Opening, cancellation, later updates and restart cause no clipboard write or upload.

## Distinct failure owners

Preparation retains its request identity, draft and cancellation/generation guards.
Its copy action says no run started. The executor remains responsible for workload
results. A crashed/missing-report execution controller is displayed as incomplete
evidence, retaining available controller stderr and unknown running-step outcomes;
the GUI does not rewrite its persisted report.

`manager_diagnostics` owns independent private bookkeeping under the existing
registry directory's `diagnostics` folder. `app.main` installs/restores exception
hooks and offers prior diagnostics nonmodally. Hooks record exception class/message
and frame locations without locals or source/argument values, delegate to previous
hooks exactly once, and leave routine Qt logging alone. Closure-local previous
hooks remain valid during concurrent teardown.

Thirty-two fixed record slots bound discovery. Each record is at most 64 KiB,
for at most 2 MiB of record data; stable directory/session lock files do not grow
per launch. Existing shared file locks serialize admission/dismissal and identify
active sessions. Atomic private writes retain prior data on publication failure.
Reject linked, non-file, oversized or malformed records. Never evict active or
pending reports to admit a new session; a full or inaccessible store reports that
recording is unavailable. Normal exit removes only its no-error marker; explicit
dismissal removes only the selected inactive diagnostic.

A released lease with an active marker means the GUI ended unexpectedly with no
known cause. SIGKILL/native faults may leave no traceback. It does not prove that
a workload failed, cancelled or stopped. Diagnostics never read/write run plans,
results, approval records or holds and never signal an executor. A separately
surviving executor can continue; its outcomes must be read through normal history.

## Validation

Use the checkout `.venv`, `PYTHONPATH=Python:Python/tests` and offscreen Qt for
`test_diagnostics`, `test_manager_diagnostics` and `test_diagnostics_ui`, plus the
affected results/navigation/preparation tests. Fixtures cover synthetic secrets,
paths/arguments/key boundaries, safe field extraction, byte/line/read bounds,
bad links/records, selected cases, current/saved failures, exact local copy,
cancelled/stale workers, unknown/partial delivery, abrupt owned-child exit,
concurrent hook teardown and unchanged last-valid run bytes. Only explicitly owned
disposable subprocesses may be terminated. Native first-use review is separate
from portable tests; protect/restore clipboard MIME data in memory for any actual
native clipboard check, without logging its prior contents.

The organization borrows overview-to-problem navigation from
[TeamCity](https://www.jetbrains.com/help/teamcity/investigating-and-muting-build-failures.html),
structured failure detail from [GitLab](https://docs.gitlab.com/ci/testing/unit_test_reports/),
and scoped step/log context from [GitHub Actions](https://docs.github.com/en/actions/how-tos/monitor-workflows/use-workflow-run-logs).
These are task-flow references, not execution policy or visual templates.

[Developer guide](development.md) · [User recovery guide](../user/workflows.md)
