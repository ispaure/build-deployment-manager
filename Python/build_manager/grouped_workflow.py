"""Attach exact tasks to the chosen journey without changing its overview graph."""
from dataclasses import dataclass, field
import json
from .proposed_workflow import propose


@dataclass(frozen=True)
class GroupedWorkflow:
    phases: tuple
    members: dict
    references: dict = field(default_factory=dict)
    unassigned: tuple = ()
    notes: dict = field(default_factory=dict)
    effect: str = 'test'
    grouped: bool = True
    proposed: bool = False
    journey: dict = field(default_factory=dict)
    backend: str = ''


def retained_proposal(plan, capability=None):
    """Reconstruct old runs from their retained choices, never the current form."""
    capability = capability or {}
    journey = getattr(plan, 'journey', {})
    values = {**plan.source.get('run_overrides', {}),
              **plan.source.get('effective_settings', {}).get('values', {})}
    if not journey:
        return propose(capability=None, goal='advanced', revision=str(plan.source.get('selection') or plan.source.get('revision') or 'working-tree'),
            platforms=[], destinations=[], backends={}, operation=plan.operation,
            platform=str(plan.adapter.get('platform', '')), backend=plan.backend)
    targets = journey['platforms']
    destinations = journey['destinations']
    # Descriptor order is also the configuration's checkbox order.
    selected_targets = [key for key in capability.get('platforms', {}) if key in targets]
    selected_targets += [key for key in targets if key not in selected_targets]
    selected_destinations = [key for key in capability.get('destinations', {}) if key in destinations]
    selected_destinations += [key for key in destinations if key not in selected_destinations]
    resolved = dict(capability,
        platforms={key: dict(capability.get('platforms', {}).get(key, {}),
            backend=journey.get('executions', {}).get(key, {}).get('backend', plan.backend)) for key in selected_targets},
        destinations={key: dict(capability.get('destinations', {}).get(key, {}),
            label=capability.get('destinations', {}).get(key, {}).get('label', key.title()),
            platforms=destinations[key].get('platforms', list(targets))) for key in selected_destinations})
    recipients = {}
    for destination in resolved['destinations'].values():
        name = destination.get('recipient_field')
        if name and values.get(name):
            try:
                people = json.loads(values[name])
            except (ValueError, TypeError):
                people = []
            if isinstance(people, list) and all(isinstance(person, str) for person in people):
                recipients[name] = people
    return propose(capability=resolved, goal=journey['goal'],
        revision=str(plan.source.get('selection') or plan.source.get('revision') or 'working-tree'),
        platforms=selected_targets, destinations=selected_destinations,
        backends={key: row['backend'] for key, row in resolved['platforms'].items()},
        recipients=recipients, values=values)


def group_workflow(plan, capability=None, proposal=None):
    """The intent graph stays identical; execution edges exist only inside cards."""
    overview = proposal or retained_proposal(plan, capability)
    nodes = overview.phases
    members = {node.id: [] for node in nodes}
    references = {node.id: [] for node in nodes}
    notes = {}
    phases = {phase.id: phase for phase in plan.phases}
    journey = getattr(plan, 'journey', {})
    ancestors = {}
    for phase in plan.phases:
        ancestors[phase.id] = set(phase.dependencies)
        for parent in phase.dependencies:
            ancestors[phase.id].update(ancestors[parent])
    owners = {}

    def attach(key, candidates):
        for phase_id in candidates:
            if phase_id not in phases:
                continue
            if phase_id not in owners:
                owners[phase_id] = key
                members[key].append(phase_id)
            elif owners[phase_id] != key and phase_id not in references[key]:
                references[key].append(phase_id)

    if 'source' in members:
        attach('source', [phase.id for phase in plan.phases if getattr(phase, 'section', '') == 'source'])
    for target, gates in journey.get('platforms', {}).items():
        key = 'platform.' + target
        if key not in members:
            continue
        work = set(gates) | set(journey.get('executions', {}).get(target, {}).get('steps', ()))
        for phase_id in tuple(work):
            work.update(ancestors[phase_id])
        attach(key, [phase.id for phase in plan.phases if phase.id in work])
    for destination, row in journey.get('destinations', {}).items():
        cards = [node.id for node in nodes if node.id.startswith('deliver.' + destination + '.') or node.id == 'deliver.' + destination]
        if not cards:
            continue
        if len(cards) == 1:
            attach(cards[0], row['steps'])
        else:
            # No action-to-recipient mapping is promised by the journey contract.
            # Preserve each visible recipient card without inventing that identity.
            for key in cards:
                attach(key, row['steps'])
                notes[key] = 'These recipient cards share the destination’s declared actions. The project did not declare an action-to-recipient mapping; inspect the exact action before approval.'
    # A package's declared label is a presentation identity, unlike a command or
    # an inferred step-ID prefix. Unmatched work stays accessible below the map.
    packages = [node for node in nodes if node.id.startswith(('package.', 'prepare.'))]
    for phase in plan.phases:
        if phase.id in owners:
            continue
        matches = [node for node in packages if getattr(phase, 'label', '') and node.label == phase.label]
        if len(matches) == 1:
            attach(matches[0].id, [phase.id])
    for phase in reversed(plan.phases):
        if phase.id in owners:
            continue
        downstream = {owners[key] for key in owners if phase.id in ancestors[key]}
        package_cards = [node.id for node in packages if any(
            child.id in downstream and node.id in child.dependencies for child in nodes)]
        candidates = package_cards or [key for key in downstream if key.startswith(('package.', 'prepare.'))]
        if candidates:
            for key in dict.fromkeys(candidates):
                attach(key, [phase.id])
        elif len(downstream) == 1:
            attach(next(iter(downstream)), [phase.id])
    if 'operation' in members:
        attach('operation', [phase.id for phase in plan.phases if phase.id not in owners])
    # Display tasks in actual plan order even when assigned by reverse ancestry.
    order = {phase.id: index for index, phase in enumerate(plan.phases)}
    return GroupedWorkflow(tuple(nodes),
        {key: tuple(sorted(value, key=order.get)) for key, value in members.items()},
        {key: tuple(sorted(value, key=order.get)) for key, value in references.items()},
        tuple(phase.id for phase in plan.phases if phase.id not in owners), notes, backend=plan.backend)
