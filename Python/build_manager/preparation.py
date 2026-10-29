"""Normalize workflow choices without importing widgets or project modules."""
from dataclasses import dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class WorkflowSelection:
    goal: str = 'advanced'
    operation: str = ''
    platform: str = ''
    backend: str = ''
    revision: str = 'working-tree'
    pattern: str = ''
    release_tag: str = ''
    build_override: int = 0
    suite: str = ''
    selected_platforms: tuple[str, ...] = ()
    selected_destinations: tuple[str, ...] = ()
    platform_backends: Mapping[str, str] = field(default_factory=dict)
    run_options: Mapping[str, bool] = field(default_factory=dict)
    run_overrides: Mapping[str, str] = field(default_factory=dict)

    @classmethod
    def from_choices(cls, choices: Mapping[str, Any]) -> 'WorkflowSelection':
        # Snapshot mutable selections before sending work to another thread.
        values = dict(choices)
        for name in ('selected_platforms', 'selected_destinations'):
            if name in values:
                values[name] = tuple(values[name])
        for name in ('platform_backends', 'run_options', 'run_overrides'):
            if name in values:
                values[name] = dict(values[name])
        return cls(**values)


@dataclass(frozen=True)
class PreparationRequest:
    """An adapter request, never an executable plan or an authorization."""
    selection: WorkflowSelection
    options: Mapping[str, Any]
    journey: bool = False

    def prepare(self, project):
        selection = self.selection
        if self.journey:
            destinations = list(selection.selected_destinations) if selection.goal == 'deliver' else []
            return project.make_journey(selection.goal, list(selection.selected_platforms),
                                        destinations, **self.options)
        operation = 'Build' if selection.goal == 'build' else selection.operation
        return project.make_plan(operation, selection.platform, selection.backend, **self.options)


def preparation_request(selection: WorkflowSelection, *, integrated=False,
                        include_backends=True) -> PreparationRequest:
    """Share option normalization while keeping GUI/preset admission explicit."""
    options = dict(revision=selection.revision, pattern=selection.pattern,
                   release_tag=selection.release_tag,
                   build_override=str(selection.build_override) if selection.build_override else '')
    if selection.run_overrides:
        options['run_overrides'] = dict(selection.run_overrides)
    journey = integrated and selection.goal in {'validate', 'deliver'}
    if journey:
        if include_backends and selection.platform_backends:
            options['backends'] = {target: selection.platform_backends[target]
                                   for target in selection.selected_platforms}
    elif selection.goal == 'build':
        options['pattern'] = ''
    else:
        if selection.suite:
            options['suite'] = selection.suite
        options.update(selection.run_options)
    return PreparationRequest(selection, options, journey)


def validate_gui_selection(project, selection, *, integrated):
    """Validate declared combinations before the adapter worker starts."""
    if integrated:
        from .journeys import request
        request(project.journey_capability, selection.goal, selection.selected_platforms,
                selection.selected_destinations if selection.goal == 'deliver' else ())
        return
    operation = 'Build' if selection.goal == 'build' else selection.operation
    operations = getattr(project, 'operations_for', lambda _: project.operations)(selection.platform)
    if operation not in operations or selection.backend not in project.backend_options(selection.platform, operation):
        raise ValueError('This platform, operation and execution host do not work together. Your choices are retained; choose a supported combination explicitly.')
    if selection.goal == 'deliver':
        raise ValueError('This project has not declared integrated delivery. Choose Advanced operation and a project workflow; review its actual destinations.')
