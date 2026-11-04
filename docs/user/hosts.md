# Host capabilities and Android

Local policy is explicit: macOS supports native macOS, Android and iOS with verified
prerequisites; Linux supports native Linux; Windows supports native Windows.
Local Android testing on Linux and Windows is currently **Unavailable**, including
x64. Finishing implementation and native acceptance is deferred to separate
Windows and Linux follow-up briefs. Use macOS for local Android testing. Hosted targets are separate. Capability states distinguish unsupported,
unconfigured, unavailable and ready. No remote, architecture or device fallback is
selected implicitly. VM adapters are macOS-only and retain all owner holds.
New [dedicated Fedora and Windows machines](virtual-machines.md) can be created
under the manager checkout's ignored `VM/` folder with explicit ownership receipts;
their initialization does not adopt or change held/personal guests.

Android SDK/JDK paths are explicit. Image ABI is checked against actual host CPU;
acceleration is Hypervisor.Framework, KVM or WHPX according to host. Missing tools,
images or acceleration stop before creating a device. SDK installation and license
acceptance are operator setup; the transport never copies a global SDK/AVD cache.

`python -m build_manager.android_runner --sdk SDK --workspace OWNED_FRESH_DIRECTORY
--image IMAGE_ID --model MODEL --result REPORT` runs a single supervised disposable
session; `--apk HARMLESS_TEST_APK` optionally installs a fixture into that new device.
The single-session route retains Windows process ownership across readiness and
test actions. Cleanup verifies a unique AVD name and process creation identity,
preserves logs/receipts and deletes only owned AVD/user state. Personal devices,
existing AVDs and installed app data are preserved.

Native Fedora/Windows manager launcher, locking and process checks are separate
from Android acceptance. The current release records Linux/Windows Android as a
known limitation. Never create/access held guests to obtain coverage. Project-owned
native suites retain their own supported-toolchain limits.

## Explicit GitHub-hosted Android context

Hosted adapters may explicitly construct `AndroidEmulator` with
`execution_context='github-actions'`. The default remains `local`; runner
environment variables alone never enable local Linux or Windows Android testing.
The opt-in requires an actual Linux x64 host, process-level GitHub runner markers
(`GITHUB_ACTIONS=true`, `RUNNER_OS=Linux`, `RUNNER_ARCH=X64`), read/write access to
an actual `/dev/kvm` device, complete SDK/image files, a native x86_64 image ABI
and a successful emulator acceleration check reporting usable KVM. Caller-supplied
emulator environment overrides cannot supply admission markers. Missing prerequisites
fail before AVD creation; acceleration or architecture fallbacks are not selected.

Owned leases retain execution context, host identity and verified acceleration
alongside the existing unique AVD/process ownership evidence. This provider context
does not alter local capability reporting. Portable admission/lifecycle tests are
separate from actual GitHub emulator acceptance; the consuming hosted workflow
must still demonstrate native execution before claiming that coverage.

## Adapter process supervision prerequisites

POSIX hosts need the system `ps` utility with PID, process-group and state output
for owned bridge-session teardown. macOS includes it; minimal Linux images must
provision the distribution's process tools (for example, Fedora's `procps-ng`).
The project/image owner installs this host dependency, not the SDK or a project
virtual environment. The manager checks inventory before launching an adapter;
missing or unusable inventory stops the request before project effects. Teardown
remains fail closed if inventory later becomes unavailable. Windows uses its
owned job mechanism and does not require `ps`.

## Android emulator host architecture

Android guest image ABI, vendor host support and manager availability are separate
checks. macOS ARM64/x64 can proceed to SDK/image/acceleration verification. Linux
and Windows x64 report **Unavailable** because implementation and native validation
are deferred. This release limitation applies even when a project marks its SDK
ready. Starting a session stops before tools run or an AVD is created. Native Linux/
Windows testing remains available; separately declared hosted choices stay visible.

Linux ARM64 and Windows ARM64 also lack supported official emulator host binaries.
Google's [host requirements](https://developer.android.com/studio/install) and
[Parallels' Windows ARM limitations](https://kb.parallels.com/en/129497) describe
those vendor constraints. The x64 follow-ups must verify compatible images and
KVM/WHPX acceleration on real x64 machines before enabling those manager paths.
No translated-binary, physical-device or hosted fallback is selected automatically.

## Apple tools that do not exit

Simulator inventory and lifecycle commands have explicit deadlines. If a command
exceeds its deadline, the manager requests termination and allows at most three
more seconds for that process to exit. If macOS still cannot retire it, the
operation fails with the unresolved process ID and an unverified outcome. It does
not retry the command, infer completion from partial output or wait indefinitely.

Preserve that failure and inspect the reported process on the Mac before retrying.
A process stuck in kernel exit can require host recovery; repeatedly launching
more commands does not establish readiness. Resume only after the selected tools
can complete normally. Existing personal simulators are never reset or deleted
as a workaround.

Disposable emulator port allocation and console registration are serialized on
the same host, including starts from different checkouts or SDKs. This keeps
another manager run from selecting a console/ADB pair while it is being bound.
Once the unique console name is verified, guest boots may proceed concurrently. Cleanup verifies the AVD name before console commands;
if a serial belongs to another run, only the recorded process may be stopped,
after checking its creation time and unique AVD token.

The disposable backend defaults to a 240-second boot deadline. An owning native
probe may explicitly select a longer `startup_timeout`, up to 3600 seconds, for
a busy host; boot-completion and AVD/process identity checks remain required.

Owning probes may explicitly select `gpu="swiftshader"` when the SDK auto renderer
fails to initialize a display. The selected renderer is recorded in the device
lease. This selects software graphics explicitly; native ABI and hardware CPU
acceleration checks still apply. The default remains `gpu="auto"`.

Disposable Android devices use the SDK-supported even console ports 5554–5584,
with the following port reserved for ADB. Advertised offline transports also
reserve their ports. If that range is occupied, startup reports capacity rather
than selecting an unsupported port.
