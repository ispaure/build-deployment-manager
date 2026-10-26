# Validation scope and remaining acceptance

## October 25 refactoring follow-up

Manager runtime commit `bb34d5f` passes all 158 contracts on macOS and on the
dedicated Fedora 44 ARM64 and Windows 11 ARM64 guests. Windows uses x64 CPython
3.12.2 under emulation and retains three explicit POSIX-only skips. These are
native-platform process/Qt contracts with offscreen presentation; they do not
certify physical UI interaction or accessibility-reader behavior.

The guest plans also run Logistics' focused evidence-collection/cleanup fixtures,
collect the original manager result and logs, then remove their owned guest
workspaces. The existing public Windows tool cache is intentionally retained.
Both real backend flows pass. Tests cover responsive background artifact checks,
cancelled/stale review, changed files during the approval dialog and refusal to
launch an external effect. Those fixtures use harmless processes, with no upload
or publication. The exact reviewed manager/commonUtils pins are recorded by each
retained run; owning project source can still be a labelled development snapshot.

Generic contracts exercise real subprocess/GUI chains, failure, timeout,
cancellation with descendants, cleanup, locking, redaction, isolated adapters,
settings migration, workflow restart, exact artifact review, partial provider
outcomes and resource contention between two manager processes. Controlled
transports cover accepted requests followed by connection loss without duplicates.
These checks do not establish unavailable native-platform or publication coverage.

macOS acceptance includes real launcher startup from another directory and a
checkout path with spaces/Unicode, an actual Logistics adapter plan through the
external engine and Qt route, and an inert APK installed in an owned disposable
Android emulator with verified cleanup. Current source/dependency identities and
actual outcomes belong to each ignored run report, not to historical green claims.

Dedicated Fedora and Windows ARM64 guests provide native launcher, process-tree,
locking, atomic-state, Unicode-path and cleanup acceptance. Their isolated Python
3.12.2 environments run the same pinned manager/commonUtils sources. Windows uses
native junction fixtures without Developer Mode or symlink privilege changes;
POSIX signal-only cases remain explicit skips, alongside Windows process-job checks.
Project filesystem suites may additionally require actual Windows symbolic links.
The dedicated VM setup supports explicitly approved Developer Mode and preserves
that approval across recreation, as described in [VM setup](virtual-machines.md).
Its normal-user symlink probe is separate from completing the project's suite.
Report publication retries transient Windows sharing conflicts for at most two
seconds, and closing a project panel cancels/drains its history reader before
releasing project files. Raw attempts and corrections remain in ignored evidence.

Linux/Windows Android testing is intentionally unavailable in this release,
including on x64. Its remaining implementation and native validation are recorded
as known limitations and deferred to separate Windows and Linux follow-ups.
Existing ARM64 guests must not be presented as Android passes. See [dedicated test machines](virtual-machines.md).
The held Fedora guest and Windows Testbed are not substitutes.
Blue Hole requires a supported Blender 5.2.2 isolated enable/import smoke test;
portable tests and an inspected ZIP do not replace that gate. Missing environments
keep the applicable follow-up acceptance open. No push, live hosted
dispatch, tester notification or release upload is used to manufacture evidence.

Project source, packaging, release gates and native suite policy remain in the
owning repositories. Passing tests never publishes. App Store/Google Play remain
unimplemented. No manager self-release/self-update pipeline, visual workflow editor,
credential sync or new remote-agent service is part of this implementation.

## Guided UI validation and adoption boundary

The [twelve implementation briefs](ui-improvement-plan.md) now have manager-side
support for staged configuration/review, suite selection, preseeded step status,
independent live clocks, JUnit case evidence, filtering and failure detail, direct
retained delivery review, background history, and accumulated attempt timing.
Portable tests use real harmless Qt-to-CLI subprocesses to exercise failure gates,
case reports on nonzero exit, exact suite forwarding, stale selections, declined
approval, changed artifacts, unknown outcomes, recovery and read-only history.
Offscreen Qt screenshots cover configure, review, mixed results and compact sizing;
raw captures and test output belong under ignored test-results.

Briefs 1–11 are implemented in this repository. Brief 12 now has source adoption
in Logistics and Blue Hole: descriptor catalogs, matching suite routing, JUnit
emission, complete release-gate inventories, exact-package Blender acceptance and
separately reviewed deliveries. Real registered-adapter portable runs verify case
capture through project-owned commands and interpreters. Controlled tests cover
missing native hosts, source/package mismatch, required skips, incomplete device
families, and interrupted distribution attempts.

Real Blender acceptance uses an explicitly selected supported 5.2.2 runtime and
the exact prepared ZIP in an isolated profile. Runtime availability alone does
not satisfy that gate. Native mobile acceptance and exact-source hosted receipts are separate
requirements; an absent iOS runtime receipt blocks reviewed TestFlight delivery.
Owning dependency pins select a locally reviewed manager commit containing reporting;
that commit and its commonUtils pin must be available remotely before fresh hosted
setup can use them. Local pinning does not push those commits. No hosted action, release, personal-device
installation or tester upload was used to manufacture acceptance. Offscreen UI
checks do not prove native OS interaction or accessibility-reader behavior.

## Android host preflight

Host capabilities distinguish the emulator executable's supported host architecture
from its selected Android image ABI. Linux/Windows hosts report
Unavailable before SDK commands or workspace creation, including when project
configuration claims readiness. A separately declared hosted option remains visible.
The dedicated VM readiness view uses the guest's actual architecture for this check.
See [host requirements](hosts.md#android-emulator-host-architecture). Current implementation briefs close with this explicitly deferred scope; the
platform follow-ups require real Android acceptance before enabling x64 support.

## Logistics native desktop acceptance — 2026-10-25

The dedicated Fedora 44 ARM64 and Windows 11 ARM64 guests completed the declared
Logistics platform checks. Windows uses x64 CPython 3.12.2 under emulation; Fedora
uses native ARM64 CPython 3.12.2. Both use Qt 6.12. This establishes the selected
guest coverage, independently of physical x64 hardware or fresh Ubuntu acceptance.

Failed full attempts remain preserved. Their unchanged shared, compression and
packaging results were reused after checking dependency, suite and package inputs.
At Logistics `14e9c13c` / commonUtils `b105857d`, all 117 cases in the 12 corrected
or affected application modules passed on each guest. The current manager
`798587b` passed 154 native contracts on Fedora and Windows; Windows reports three
explicit POSIX-only skips. Actual guest probes also verified recovery of exits 0
and 7 after transport loss, no duplicate execution, and cancellation before child
admission. The final ordinary Logistics backend runs passed setup, focused tests,
report retrieval and owned cleanup (Windows `12cc9598`, Fedora `14e9c13c`).

| Verified check | Windows seconds | Fedora seconds |
| --- | ---: | ---: |
| Shared suite, unchanged pinned inputs | 599.92 | 128.40 |
| Compression parity | 31.06 | 4.67 |
| Release/package checks | 23.50 | 1.48 |
| Current manager contracts, 154 cases | 65.32 | 14.55 |
| Final focused backend flow, including setup/transfer/collection | 68.02 | 39.41 |

Windows packaging includes actual extracted batch-launcher execution and CRLF
checks. Fixes cover large-plan stdin transfer, explicit Qt widget ownership,
read-only Git scratch cleanup, original ZIP entry validation, portable fixtures,
asynchronous reader teardown and durable Windows invocation receipts. Evidence
transfer archives are removed after verified host collection. Raw attempts,
per-case timings and cleanup proofs stay under ignored `test-results/logistics-native/`.
Later source changes retain their own acceptance requirements. Android x64 and
post-GitHub integration remain separate follow-ups; no push or hosted dispatch
was used for this local acceptance.
