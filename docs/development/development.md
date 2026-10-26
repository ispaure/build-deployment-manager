# Developing the build manager

Start with [setup](../user/setup.md) to create this checkout's locked environment.
The manager's source root is `Python`; import `build_manager`, never
`Python.build_manager`. Its commonUtils submodule is independent of the one in
the project being built. Keep each project's interpreter and dependency pins.

## Follow one run through its owners

| Stage | Source owner | Important boundary |
| --- | --- | --- |
| Register/inspect/trust a checkout | `registry.py`, `cli.py` | Parse descriptors before executing adapter code; trust is checkout-specific |
| Ask the project for a plan | `bridge.py` | Project interpreter, structured stdin/stdout JSON, no in-process project import |
| Describe work | `models.py` | Versioned Plan/Phase data, declared effects/dependencies/resources |
| Execute it | `executor.py`, `resources.py`, `locking.py` | Process ownership, dependency gates, bounded concurrency, cleanup |
| Keep and resume evidence | `history.py`, `workflows.py`, `retention.py` | Checksums, original plan, unknown outcomes and durable holds |
| Present it | `configuration_ui.py`, `ui.py`, `run_ui.py`, `settings.py` | Selection values, Qt-thread ownership and explicit review |
| Retain a GUI run/review | `run_session.py`, `review.py` | Parented process/timers and cancellable verification; stale selections cannot approve work |
| Reach another host | `parallels.py`, `windows_guest.py`, `guest.py` and platform adapters | Owned guest work, durable outcomes and actual native acceptance |

The engine does not decide which Logistics tests, signing identities or release
destinations are correct. A project adapter supplies that policy. See
[adapter contracts](adapters.md), [test organization](test-organization.md)
and [provider boundaries](providers.md) before adding another abstraction.

## Run a harmless plan before changing an adapter

Run this with the installed manager interpreter from its Git checkout. It creates
all outputs in a disposable directory, uses no registration or credentials and
does not install, upload or dispatch anything.

```python
import json
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory
from build_manager import Phase, Plan

with TemporaryDirectory() as temporary:
    root = Path(temporary)
    plan = Plan(
        project='Example', operation='Harmless smoke',
        source={'description': 'disposable example'},
        phases=(Phase('hello', (sys.executable, '-c', "print('hello')"),
                      str(root), timeout=30),),
        workspace=str(root / 'workspace'),
    )
    plan.save(root / 'plan.json')
    subprocess.run([sys.executable, '-m', 'build_manager',
                    str(root / 'plan.json'), '--output', str(root / 'results')],
                   check=True)
    report = json.loads((root / 'results/result.json').read_text())
    assert report['status'] == 'passed'
    assert report['phases'][0]['exit_code'] == 0
```

Use structured arguments even for a simple command. Shell quoting in a string
would change the trust and portability contract. Output directories belong to a
single run; choose a fresh one or use the explicit resume workflow.

## Make one contract change

First identify the invariant: for example, an uncertain external outcome must
not be repeated, a cancelled child must retire, or a changed artifact must block
approval. Add a fixture that exercises that behavior through the owning layer.
Keep UI construction out of headless modules and avoid importing a consumer to
obtain its defaults. Add an adapter field only if an existing field cannot express
the requirement, and preserve schema/API compatibility deliberately.

For GUI changes, retain native Qt parents and signals while moving responsibilities.
The panel already delegates its board to `RunView`; an extraction should expose
clear inputs/events rather than let a new mixin read all panel attributes.
Run focused UI lifecycle checks after changing ownership, including closing during
preparation/history reads and normal process completion.

## Select validation by behavior

From this checkout, with its locked environment:

```sh
QT_QPA_PLATFORM=offscreen .venv/bin/python -m build_manager.contracts
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s Python/tests -p test_guided_ui.py -v
.venv/bin/python -m unittest discover -s Python/tests -p test_workflows.py -v
```

On Windows use `.venv\Scripts\python.exe`; set `QT_QPA_PLATFORM` through the
shell's environment syntax for offscreen checks. Process/transport fixtures are
portable contracts, not proof that a VM or personal device passed. Native Windows
process jobs, guest recovery and OS GUI ownership need their real platform checks.
Use only explicitly authorized test hosts; never substitute a held personal VM.

Then run the affected consumer adapter tests with that project's interpreter and
pin. A manager-only pass cannot establish its release gate inventory. The
[validation guide](validation.md) records actual native coverage and remaining
limits separately from the test commands above.

## Update the right guide

Shared engine behavior belongs in this wiki; project suites, snapshot creation,
signing and storage policy belong in the project. commonUtils APIs stay in that
library's wiki. Update [operator guidance](../user/user.md) when a change affects
review, retries or troubleshooting. Keep every folder's same-named landing linked
from its parent. Raw logs, screenshots and timing reports stay under ignored
`test-results/`; public pages explain reproducible scope instead of linking them.

- [Current refactoring audit](refactoring.md)
- [Documentation home](../docs.md)

## Further reading

- [Integrated validation and delivery contract](journey-contract.md)
- [Historical data and migration](migration.md)
- [Bounded scheduling and resource ownership](scheduling.md)
- [Discovering project and dependency tests](test-manifests.md)
- [Guided testing and delivery implementation plan](ui-improvement-plan.md)
- [UX redesign: implementation audit and second pass](ux-redesign-audit.md)
- [UX redesign brief: validation and coordinated delivery](ux-redesign-brief.md)
