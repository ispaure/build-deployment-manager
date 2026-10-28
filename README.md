# Build Deployment Manager

Manage builds, testing and reviewed release/deployment plans for trusted local projects.

Start with the [documentation wiki](docs/docs.md), [setup](docs/user/setup.md), and
[adapter contract](docs/development/adapters.md). Python 3.12.2 and a pinned commonUtils Git
submodule are required. The headless engine has no Qt dependency; the local GUI
environment is locked separately. Projects retain their own environments.

Use the platform launcher to open the GUI and register a trusted project checkout.
Adding it authorizes its adapter to run in that project's interpreter.
Named workflows capture source/settings, retain results,
pause for artifact review and support safe restart. Resource declarations bound
parallel work. See [workflow recovery](docs/user/workflows.md) and
[current validation scope](docs/development/validation.md).

For AI agents and scripts, use the [CLI](docs/user/cli.md) to discover supported
work, prepare and run plans, inspect compact JSON errors, read bounded logs and
resume reviewed delivery. The [Python API](docs/development/automation-api.md)
exposes the same headless execution and evidence mechanisms.
