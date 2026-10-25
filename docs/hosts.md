# Host capabilities and Android

Local policy is explicit: macOS supports native macOS, Android and iOS with verified
prerequisites; Linux supports native Linux/Android; Windows supports native Windows/
Android. Hosted targets are separate. Capability states distinguish unsupported,
unconfigured, unavailable and ready. No remote, architecture or device fallback is
selected implicitly. VM adapters are macOS-only and retain all owner holds.

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

Portable tests do not establish native Linux or Windows launcher, lock, process or
Android acceptance. Missing permitted hosts keep brief 08 and dependent integrated
acceptance open. Never create/access the held Fedora or Windows Testbed guests to
obtain that coverage. Project-owned native suites retain their own supported-toolchain
limits even when the generic Android transport supports another host.
