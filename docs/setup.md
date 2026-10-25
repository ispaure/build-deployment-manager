# Setup and launch

Initialize the pinned dependency with `git submodule update --init --recursive`.
Install Python 3.12.2 and uv, then run `uv sync --locked` at the repository root.
The `.venv` belongs to this manager. No project or Blender environment is used
for manager dependencies. Ordinary setup uses the lockfile and never pulls Git
or changes a branch. Preserve local submodule changes before initialization.

For authorized local Fedora/Windows testing, use the manager's
[dedicated test machines](virtual-machines.md) controls. Their VM bundles and
private installation state stay in the ignored checkout-local `VM/` directory.

Run headless plans with `.venv/bin/python -m build_manager PLAN --output RESULTS`.
Plans are trusted executable configuration, not incoming documents. Inspect the
source, commands and destinations first. External effects require `--confirm`.
On Windows use `.venv\Scripts\python.exe`. An explicit editable installation
with `python -m pip install --no-deps -e /path/to/manager` supplies the headless
engine to an existing project interpreter without changing its dependencies.

Run generic contracts with `.venv/bin/python -m build_manager.contracts`.

## GUI launchers

Double-click `LaunchBuildManager_MAC.command`, run
`bash LaunchBuildManager_LINUX_UV.sh`, or use `LaunchBuildManager_WIN.bat`.
The wrappers delegate runtime/environment setup to pinned commonUtils with
`launch_config.ini`. They resolve their checkout from their own location, pass
application arguments separately and return the application's exit code.
`--smoke-exit --registry PATH` performs a harmless GUI startup/normal-close check.
Native Linux/Windows acceptance requires permitted real hosts; syntax and portable
fixtures alone do not establish it. Missing config/submodule diagnostics stop
before dependency setup. For per-machine launch overrides, set
`COMMONUTILS_PERSONAL_CONFIG_FILE` to a private INI; see commonUtils' launcher guide.

Execution uses an identifiable Git checkout and initialized commonUtils so results
can record both revisions and dirty identities. Use editable installation for
project integration; an installation without those Git identities stops with a
setup message before executing work. This does not require a manager release or
self-update service.
