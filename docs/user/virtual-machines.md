# Dedicated Fedora and Windows test machines

Open **Test machines** in the manager window. Select the manager source checkout
and Linux or Windows, then **Create or recover**. The machines are named
**Build Deployment Manager (Linux)** and **Build Deployment Manager (Windows)**.
Their bundles, disks, installation media, credentials and receipts live under
the checkout's ignored `VM/` directory. This directory is deliberately excluded
from Git and releases. Keep enough free space for two expanding guest disks.

## Ownership and recovery

The headless `VM` base class owns inventory, receipts, storage checks, bounded
Parallels calls, locking and power controls. `LinuxVM` and `WindowsVM` own their
initialization and readiness requirements. Only the recorded UUID at the expected
bundle path is operated. A same-named guest without this checkout's receipt, a
moved bundle or a conflicting inventory entry stops setup instead of adopting it.

Create or recover reuses an existing owned guest, registers a surviving owned
bundle when its registration is missing, and creates a new guest when both are
missing. Interrupted hardware configuration can be completed while stopped.
Initialized guests retain their media path, checksum and initialization recipe.
If their bundle disappears, recovery reconstructs a fresh installation from that
verified media; unavailable or changed media stops recreation explicitly. Windows
reuses its checksum-recorded private setup ISO rather than generating another login.
Surviving disks are never silently replaced. A damaged or partially imported
disk requires inspection; automatic recovery does not mean automatic deletion.
All initialization and power mutations share one checkout-level lock.

Starting an owned suspended guest resumes its existing session. A selected test
run does this automatically only after matching the manager's ownership receipt,
UUID and bundle path. The CLI and Test machines Start action use the same power
boundary. Busy transitions still stop the operation; suspended personal or held
guests require an explicit operator action in Parallels. Guest readiness and native
test results are checked afterward; a successful resume does not imply either.

Fresh guests start with blanket host isolation and host folders, profiles,
clipboard and cloud sharing disabled. Parallels guest commands require the
blanket isolation setting to be released separately; the manager does not change
it implicitly. **Allow guest test commands…** describes the boundary change and
requires an explicit operator decision; the CLI equivalent requires
`enable-guest-commands --approve-guest-commands`. The narrower sharing controls
stay disabled. The guest's initial
SSH credential or Windows test login is private to `VM/`; it is never included
in command previews or result summaries. Existing personal/held VMs are not used,
cloned, unlocked, started or modified by dedicated-machine setup.

## Fedora initialization

Use a checksum-verified Fedora ARM64 cloud qcow2 image from the
[Fedora Cloud download page](https://fedoraproject.org/cloud/download/).
Choose the image and its vendor SHA-256, then **Initialize Fedora cloud image**.
This requires `qemu-img`, Parallels' disk tool and macOS `hdiutil`. A fresh sparse
64 GiB disk receives the verified image; a NoCloud seed installs Python, Git,
build dependencies, Xvfb/Qt system dependencies and bundled Parallels Tools.
An SSH key is generated for this checkout; password login remains disabled.
The guest uses its own package manager and environment, without host-home sharing.

The cloud route is only for a new, stopped, never-started VM. Repeating a completed
initialization reuses it. Do not use it to reset a previously installed machine.
Alternatively attach a verified Fedora installer ISO and finish its normal setup.
ARM64 Fedora is native ARM Linux coverage; it is not x86 Linux coverage.

## Windows initialization

Obtain an ARM64 ISO and its published checksum from
[Microsoft's Windows download page](https://www.microsoft.com/en-us/software-download/windows11arm64).
Choose the ISO and SHA-256, then **Initialize fresh Windows guest**. This route
is restricted to a stopped VM that has never been started: its answer file
partitions the new empty disk, installs Windows 11 Pro and configures the local
test account. Windows licensing/activation remains the owner's responsibility;
no product key or activation bypass is provided. Developer Mode is off by default.
For a manually managed installation use **Verify and attach installer**.

Filesystem suites that create symbolic links require explicit approval of Windows
Developer Mode. For the running, recorded Windows guest, use
`windows enable-symlink-testing --approve-developer-mode --checkout /path/to/build-deployment-manager`
with `python -m build_manager.vm`. This changes only its
`AllowDevelopmentWithoutDevLicense` registry value and saves the approval in
protected `VM/windows-policy.json`, outside the disposable guest bundle. Recovery
and fresh initialization reuse this policy and generate a separate checksum-recorded
symlink-enabled setup ISO. Retained default setup media is never overwritten.
Keep the policy file when deleting a guest bundle; deleting all VM metadata loses
the approval and requires approving it again. Host sharing stays disabled.

Setup downloads checksum-pinned official Python ARM64 and MinGit installers into
`VM/media` when absent. It copies bundled Parallels guest drivers/tools and creates
a protected setup ISO. Python's Authenticode signature is also checked in the
guest before installation. A one-time automatic login runs setup and records
`C:\BDM\bootstrap.log`; sign in again if PATH has not refreshed. Test login data
is in the protected `VM/windows-login.json`, outside Git. Do not share that file
or the setup ISO. Never attach this automated disk-partitioning seed to another
guest or a reused installation.

Windows tests run as the signed-in interactive user. A running VM without a
signed-in session cannot run these checks. If guest tools return an empty failure,
the manager makes a bounded, read-only session query and reports a missing login
when confirmed. Sign in to the selected test VM before retrying; the manager does
not switch the test command to the SYSTEM account.

Recovery can inspect one exact token-owned workspace without an interactive login.
This fixed, read-only service-account query verifies the namespace and ownership
marker; it does not execute project code, run tests or remove files. Projects use
its receipt to reconcile failed setup separately from the original attempt.

## Readiness and testing

Projects that support automatic dedicated-machine selection can fill empty Fedora
and Windows settings from this checkout's ownership records and Parallels
registration. Discovery verifies the bundle location without starting the guest
or checking its OS. Save in Project settings remembers the detected UUID in the
project's private manager profile. Existing explicit selections take precedence.
If detection is unavailable, use Create or recover here, then reopen Project settings.
Advanced Fedora container testing uses a separate explicitly configured Ubuntu host;
it is unnecessary for direct Fedora guest testing.

Start the guest and finish its OS/tool setup, then choose **Check readiness**.
**Open console** shows only the selected owned machine in Parallels for normal
installation and desktop interaction.
It verifies a running owned guest, its actual operating system, Python >=3.12
and Git, and retains an independent readiness receipt. Hardware creation alone
does not set test readiness. GUI dependencies, a desktop session, project adapters,
Android SDK/JDK/images and actual acceptance checks remain separate requirements.
Install the manager and each project into isolated guest environments using their
declared dependency pins; never use a host interpreter or discover sibling sources.

Linux readiness reports KVM availability. Both guests report Android capability
using their actual guest OS/architecture, independently of generic test readiness. Windows on ARM and nested virtualization
have platform limitations; an unavailable Android emulator must remain unavailable,
rather than falling back to a physical device, another guest or a different ABI.
See [host capabilities](hosts.md). Keep native launcher/process/locking results
distinct from Android acceptance and from controlled portable transport tests.
Save exact source/toolchain evidence under ignored `test-results/`.

Windows guest commands publish an atomic completion receipt tied to the workspace,
operation and individual invocation before returning their result. If Parallels
loses a job handle, the manager reads that receipt or supervises the matching live
worker within the original timeout. Each invocation claims admission atomically.
If no worker or receipt is found after a known lost-handle error, the controller
may resend that same invocation up to three times; duplicate admission cannot
launch the command again. Missing or mismatched completion proof remains a
failure; actual nonzero exits remain failures.
Cancellation requested before admission prevents the child from starting.
Only explicitly idempotent setup, evidence collection and owned removal retry
the known Parallels lost-handle errors, at most three times.

The same operations are available without Qt:

```sh
python -m build_manager.vm linux ensure --checkout /path/to/build-deployment-manager
python -m build_manager.vm linux initialize-cloud --checkout /path/to/build-deployment-manager --media /path/to/fedora.qcow2 --sha256 VENDOR_SHA256
python -m build_manager.vm windows initialize-windows --checkout /path/to/build-deployment-manager --media /path/to/windows.iso --sha256 VENDOR_SHA256
python -m build_manager.vm linux start --checkout /path/to/build-deployment-manager
python -m build_manager.vm linux readiness --checkout /path/to/build-deployment-manager
python -m build_manager.vm linux stop --checkout /path/to/build-deployment-manager
```

Shutdown uses ACPI, which also works before guest tools are installed. There is
no automatic forced shutdown or VM deletion. Keep installation media and initial
private credentials until setup has been verified, then retain them according to
the owner's desired recreation policy. This folder is not ordinary run scratch
and is never swept by project build retention.
