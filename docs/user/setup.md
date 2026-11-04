# Set up and launch the manager

Use this guide to open the manager from a Git checkout. You need Git, Python
3.12.2 and uv, plus internet access for packages not already cached. The GUI
requires a graphical desktop on macOS, Linux or Windows. There is no Android or
iOS manager application: mobile platforms are project build/test/install targets
controlled from a supported desktop host. See [host capabilities](hosts.md) for
the target and host combinations currently available. Project SDKs and provider
accounts are needed only for the project operations that use them.

Run commands from the **build-deployment-manager repository root**, the folder
containing this README and the platform launchers. The commands below create the
manager's root `.venv`; each registered project keeps its own environment.

## 1. Initialize the shared dependency

For a fresh checkout, run:

```sh
git submodule update --init --recursive
```

This checks out the pinned commonUtils dependency; it is not a command to upgrade
it to the newest revision. In an existing working copy, preserve any local
submodule changes before running it. A missing `Python/commonUtils` usually means
this initialization has not completed.

## 2. Install the locked environment

On macOS or Linux:

```sh
UV_PROJECT_ENVIRONMENT="$PWD/.venv" uv sync --project Python --locked --python 3.12.2
```

On Windows PowerShell:

```powershell
$env:UV_PROJECT_ENVIRONMENT = "$PWD/.venv"
uv sync --project Python --locked --python 3.12.2
```

The manifest, lockfile and Python version pin live in `Python/`. The explicit
environment path keeps the installed interpreter at the repository root. Setup
uses the lockfile; it does not pull Git changes or switch branches.

Check the command-line installation without registering or executing a project:

```sh
.venv/bin/python -m build_manager.cli --help
```

On Windows use `.venv\Scripts\python.exe` in place of `.venv/bin/python`.
Expected result: command help listing registration, planning and run commands.
If Python cannot import `build_manager`, check the working directory and repeat
locked setup using this checkout's environment.

## 3. Open the GUI and add a project

| Platform | Launcher in the repository root |
| --- | --- |
| macOS | Double-click `LaunchBuildManager_MAC.command` |
| Linux | Run `bash LaunchBuildManager_LINUX.sh` |
| Windows | Open `LaunchBuildManager_WIN.bat` |

The wrappers delegate environment setup to pinned commonUtils using
`launch_config.ini`. They resolve the checkout from their own location and return
the application's exit status. Missing configuration or shared files stops setup
with a diagnostic. For private machine-specific launcher overrides, use
`COMMONUTILS_PERSONAL_CONFIG_FILE` as described in commonUtils' launcher guide.

In the window, use **Add your first project** or **More → Add project**. Choose a
trusted checkout containing `build-project.json`, inspect the preview and add it.
Adding it authorizes its adapter to prepare work in its own interpreter. A project
with a missing environment shows setup guidance; installing its packages in the
manager environment will not repair it.

You should now see the selected project's work choices. Continue with
[your first workflow](user.md) or the [control reference](guided-ui.md).

## Command-line use and development

### Check or repair project tooling

For projects declaring the optional bootstrap actions, use **More → Project
tooling…**. This checks the project's own interpreter environments even when its
normal adapter cannot import the manager package. **Update project tooling…**
explicitly invokes that project's declared dependency repair, then refreshes the
idle project view. A blocked active environment must finish its run first.

The same route is available without the GUI:

```sh
build-manager tooling --project PROJECT
build-manager tooling --project PROJECT --update --confirm
```

Checks do not install anything. Repair uses the project's declared dependency
pin and project-owned immutable sources, rather than the GUI's running checkout.
The project owns any post-`uv sync --locked` repair, must explicitly enroll tooling
environments, and must protect in-flight interpreter leases. Ordinary app launches
are not permission to install manager tooling. No manager interpreter or sibling
checkout is substituted for the project's environment. Projects without these
optional actions continue to use their own setup guide; a missing bootstrap
interpreter also requires initial project setup.

### CLI and development entry points

Use `.venv/bin/build-manager` on macOS/Linux, or activate the manager environment
and use `build-manager`. `python -m build_manager.cli` exposes the same interface
when `python` is this installed interpreter. See the [CLI guide](cli.md).
The older `python -m build_manager PLAN --output RESULTS` interface executes an
already prepared plan. Plans contain executable commands: inspect the source,
commands and destinations before running one. External effects need confirmation.

For development, start with the [harmless plan example](../development/development.md#run-a-harmless-plan-before-changing-an-adapter).
The full generic suite is `.venv/bin/python -m build_manager.contracts`; it
includes GUI contracts and uses `QT_QPA_PLATFORM=offscreen` on headless hosts.
Execution requires manager and submodule Git identities so results can record
revisions and local edits. An archive without those identities is insufficient.

A consumer can explicitly install this reviewed engine in its existing interpreter
with `python -m pip install --no-deps -e /path/to/manager/Python`. This preserves
that consumer's dependency policy; it is separate from manager GUI setup.

## Troubleshooting and local files

| Symptom | Check |
| --- | --- |
| `uv` or Python unavailable | Install the prerequisites, then rerun locked setup |
| Missing shared launcher or commonUtils | Check submodule initialization; do not point at an unrelated checkout |
| Project interpreter unavailable | Follow that project's setup instructions |
| Native backend unavailable | Read [host requirements](hosts.md); a portable test pass cannot make a backend available |

Manager preferences and registrations live outside the checkout; see
[stored settings](user.md#remember-choices-and-save-run-presets). Preserve `.venv/`
and editable-install `.egg-info/` metadata while using the installed checkout.
Build retention belongs to project policy, using manager lease/pin mechanisms.
Do not sweep `VM/`, credentials, application data or `test-results/` as caches.
Dedicated [test machines](virtual-machines.md) have a separate authorized lifecycle.

[User guide](user.md)

## Integrate a simple command project

A repository with existing local commands can use a single command descriptor,
without a Python bridge. Use [init-project and check-project](cli.md#scaffold-and-check-a-project)
for scaffolding and explicit diagnostics. The folder preview distinguishes missing
adapter files from files that are present but have not been loaded. Registering a
folder still does not install its dependencies or run its commands.
