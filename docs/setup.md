# Setup and launch

Initialize the pinned dependency with `git submodule update --init --recursive`.
Install Python 3.12.2 and uv, then run `uv sync --locked` at the repository root.
The `.venv` belongs to this manager. No project or Blender environment is used
for manager dependencies. Ordinary setup uses the lockfile and never pulls Git
or changes a branch. Preserve local submodule changes before initialization.

Run headless plans with `.venv/bin/python -m build_manager PLAN --output RESULTS`.
Plans are trusted executable configuration, not incoming documents. Inspect the
source, commands and destinations first. External effects require `--confirm`.
On Windows use `.venv\Scripts\python.exe`. An explicit editable installation
with `python -m pip install --no-deps -e /path/to/manager` supplies the headless
engine to an existing project interpreter without changing its dependencies.

Run generic contracts with `.venv/bin/python -m build_manager.contracts`.
