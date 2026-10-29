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
