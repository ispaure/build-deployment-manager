# Build Deployment Manager

Manage builds, testing and reviewed release/deployment plans for trusted local projects.

Start with the [documentation wiki](docs/docs.md), [setup](docs/setup.md), and
[adapter contract](docs/adapters.md). Python 3.12.2 and a pinned commonUtils Git
submodule are required. The headless engine has no Qt dependency; the local GUI
environment is locked separately. Projects retain their own environments.

Use the platform launcher to open the GUI, register a checkout and explicitly
trust its project adapter. Named workflows capture source/settings, retain results,
pause for artifact review and support safe restart. Resource declarations bound
parallel work. See [workflow recovery](docs/workflows.md) and
[current validation scope](docs/validation.md).
