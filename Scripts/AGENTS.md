# Root scripts preservation

Keep this root `Scripts/` directory and existing script names and paths.
Some computers invoke root scripts directly. An absent in-repository caller
does not prove a script is unused. Do not remove, relocate or rename scripts
during cleanup without explicit authorization for that particular change.

Keep substantive documentation in the root `docs/` wiki. Generated Python/tool
caches are disposable; script sources and configuration are not.
