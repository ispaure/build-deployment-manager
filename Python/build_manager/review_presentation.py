"""Prepare review data without Qt, project imports, or changes to the execution plan."""
from collections import Counter
from dataclasses import asdict, dataclass, replace
import os
from types import SimpleNamespace

from .grouped_workflow import GroupedWorkflow, group_workflow
from .plan_summary import EXTERNAL, captured_choices, phase_title, summary_rows
from .proposed_workflow import ProposedStep, ProposedWorkflow
from .redaction import Redactor
from .workflow_presentation import display_states, plan_overview


@dataclass(frozen=True)
class ReviewOverview(GroupedWorkflow):
    card_details: dict | None = None


@dataclass(frozen=True)
class ReviewData:
    plan: object
    proposal: ProposedWorkflow | None
    identity: str
    grouped: GroupedWorkflow
    phases: dict
    titles: dict
    task_names: dict
    task_owners: dict
    dependency_rows: tuple
    preview_states: dict
    captured_choices: tuple
    captured_summary: str
    overview: str
    later_notes: dict
    shared_notes: tuple


def prepare_review_data(plan, *, fields=(), capability=None, proposal=None, redact=None):
    """Return a redacted presentation snapshot for delivery to the GUI thread."""
    if redact is None:
        filter_line = Redactor(os.environ.get(name) for name in plan.secret_environment)

        def redact(value):
            # Values are redacted independently so a PEM or password cannot
            # consume JSON syntax or another field's content.
            if isinstance(value, str):
                filter_line.private_key = False
                return filter_line(value)
            if isinstance(value, dict):
                return {key: redact(item) for key, item in value.items()}
            if isinstance(value, (list, tuple)):
                return [redact(item) for item in value]
            return value

    data = redact(plan.data())
    data.setdefault('journey', {})
    for phase in data['phases']:
        phase.setdefault('approval_required', True)
    view = SimpleNamespace(**{**data, 'phases': [SimpleNamespace(**row) for row in data['phases']]})
    if proposal is not None:
        nodes = []
        for node in proposal.phases:
            row = redact(asdict(node))
            row['dependencies'] = tuple(row['dependencies'])
            row['platforms'] = tuple(row['platforms'])
            nodes.append(ProposedStep(**row))
        proposal = replace(proposal, phases=tuple(nodes), messages=tuple(redact(proposal.messages)),
                           blockers=tuple(replace(blocker, **redact(asdict(blocker))) for blocker in proposal.blockers))
    return review_data(view, fields, capability, proposal, identity=plan.identity)


def review_data(plan, fields=(), capability=None, proposal=None, *, identity=''):
    """Build the same presentation for synchronous callers with an existing view plan."""
    phases = {phase.id: phase for phase in plan.phases}
    titles = {key: phase_title(phase) for key, phase in phases.items()}
    grouped = resolved_overview(plan, capability, proposal)
    owners = {phase_id: group for group, members in grouped.members.items() for phase_id in members}
    task_names = {}
    for members in (*grouped.members.values(), grouped.unassigned):
        task_names.update(short_names(members, titles))
    dependency_rows = []
    for key, phase in phases.items():
        parents = ', '.join(phase.dependencies) or 'Ready to start'
        if getattr(phase, 'waits_for', ()):
            parents += '; completion only: ' + ', '.join(phase.waits_for)
        effect = phase_effect(phase, plan)
        approval = effect in EXTERNAL and getattr(phase, 'approval_required', True)
        dependency_rows.append((key, (titles[key], parents, effect + (' · separate approval' if approval else ''))))
    choices = tuple(captured_choices(plan))
    destinations = [row['identity'] for row in plan.journey.get('destinations', {}).values()]
    source = plan.source.get('commit') or plan.source.get('fingerprint') or plan.source.get('revision', 'Captured source')
    mode = str(plan.source.get('selection') or 'Captured source')
    if plan.source.get('dirty'):
        mode += ' · includes edits'
    destination_summary = 'Goal: ' + plan.operation
    if destinations:
        destination_summary = 'Destinations: ' + '; '.join(destinations[:3])
        if len(destinations) > 3:
            destination_summary += f'; +{len(destinations) - 3} more in captured choices'
    captured_summary = ('Source: ' + mode + ' · ' + str(source)[:16] + '\nRuns on: '
                        + choices[1][1].replace('\n', '; ') + '\n' + destination_summary)
    _, later, shared = summary_rows(plan, fields)
    notes = {key: tuple(line for line in row['detail'].splitlines()
             if not line.startswith(('Upload', 'Deliver', 'Publish', 'Launch', 'Destination:',
                                     'Requires platforms:', 'Waits for:')))
             for row in later for key in row['keys']}
    return ReviewData(plan, proposal, identity, grouped, phases, titles, task_names, owners,
                      tuple(dependency_rows), display_states(plan, {}, preview=True), choices,
                      captured_summary, plan_overview(plan),
                      notes, tuple(shared))


def short_names(keys, titles):
    """Find each title's shortest unique suffix within its own card."""
    suffixes = {key: tuple(' · '.join(parts[-count:]) for count in range(1, len(parts) + 1))
                for key in keys for parts in (titles[key].split(' · '),)}
    # A shorter title also participates in longer comparisons, where slicing
    # returns its entire title. Equal suffix strings necessarily have the same
    # segment count, so count each distinct suffix of a title once.
    counts = Counter(suffix for choices in suffixes.values() for suffix in set(choices))
    names = {key: next((suffix for suffix in choices if counts[suffix] == 1), choices[-1])
             for key, choices in suffixes.items()}
    return {key: name[:1].upper() + name[1:] for key, name in names.items()}


def phase_effect(phase, plan):
    return phase.effect if phase.effect != 'inherit' else plan.effect


def phase_category(phase, plan):
    effect = phase_effect(phase, plan)
    section = getattr(phase, 'section', '')
    if effect == 'build' or (effect in {'test', 'inspect'} and phase.kind in {'build', 'package'}):
        return 'build'
    if effect in {'upload', 'deploy', 'publish'}:
        return 'delivery'
    if section == 'source':
        return section
    if effect in {'test', 'dispatch'}:
        return 'platforms'
    return section or 'platforms'


def retained_artifact_provenance(plan):
    retained = plan.settings.get('retained_delivery')
    if isinstance(retained, dict) and all(isinstance(retained.get(key), str) and retained[key].strip()
                                          for key in ('original_run', 'original_plan_identity')):
        return retained
    return {}


def build_description(platforms, phases, retained):
    parts = ['Reuse verified artifacts from the saved run' if retained else 'Prepare build artifacts']
    if platforms:
        parts.append('Platforms: ' + ', '.join(platforms))
    outputs = tuple(dict.fromkeys(path.replace('\\', '/').rsplit('/', 1)[-1]
                                  for phase in phases for path in phase.artifacts))
    if outputs:
        text = ', '.join(outputs[:3])
        if len(outputs) > 3:
            text += f' and {len(outputs) - 3} more'
        parts.append('Declared outputs: ' + text)
    return '\n'.join(parts)


def resolved_overview(plan, capability=None, proposal=None):
    """Adapt the active overview while preserving the dormant browser's grouping."""
    grouped = group_workflow(plan, capability, proposal)
    phases = {phase.id: phase for phase in plan.phases}
    categories = {key: phase_category(phase, plan) for key, phase in phases.items()}
    retained = retained_artifact_provenance(plan)
    fallback_platform = (plan.adapter.get('platform') or plan.settings.get('platform')
                         or plan.source.get('platform'))
    retained_targets = retained.get('recipients', {})
    default_platforms = tuple(retained_targets) if isinstance(retained_targets, dict) and retained_targets else (
        (fallback_platform,) if isinstance(fallback_platform, str) and fallback_platform else ())
    if not plan.journey:
        return operation_overview(plan, grouped, phases, categories, default_platforms, retained)
    return journey_overview(grouped, phases, categories, default_platforms, retained)


def operation_overview(plan, grouped, phases, categories, platforms, retained):
    """Split a legacy operation at changes of purpose without collapsing a DAG into a cycle."""
    operation = next((node for node in grouped.phases if node.id == 'operation'), None)
    if operation is None:
        return grouped
    members = {'source': tuple(grouped.members.get('source', ()))}
    if all(category == 'platforms' for category in categories.values()) and not retained:
        if operation.category == 'build':
            return replace(grouped, phases=tuple(replace(node, category='platforms') if node is operation else node
                                                 for node in grouped.phases))
        return grouped
    nodes = [node for node in grouped.phases if node.id == 'source']
    labels = {'build': 'Build & Package', 'platforms': 'Checks', 'delivery': 'Delivery'}
    counts = Counter()
    owners = dict.fromkeys(members['source'], 'source')
    segments = []
    has_delivery = 'delivery' in categories.values()
    for key, category in categories.items():
        if has_delivery and phases[key].kind == 'connection' and phase_effect(phases[key], plan) == 'inspect':
            category = 'delivery'
        if key in owners and category != 'build':
            continue
        if not segments or segments[-1][0] != category:
            segments.append((category, []))
        segments[-1][1].append(key)
    build_keys = {key for category, keys in segments if category == 'build' for key in keys}
    members['source'] = tuple(key for key in members['source'] if key not in build_keys)
    for key in build_keys:
        owners.pop(key, None)
    reuse_only = retained and not build_keys
    if reuse_only:
        nodes.append(ProposedStep('retained-artifacts', 'Reuse retained artifacts',
            build_description(platforms, (), retained), ('source',), platforms=platforms, category='build'))
        members['retained-artifacts'] = ()
    for category, keys in segments:
        counts[category] += 1
        key = 'operation' if len(segments) == 1 and not reuse_only else category + '.' + str(counts[category])
        phase_rows = [phases[step] for step in keys]
        parents = tuple(dict.fromkeys(owners[parent] for phase in phase_rows
            for parent in (*phase.dependencies, *getattr(phase, 'waits_for', ())) if parent in owners))
        if reuse_only and category == 'delivery':
            parents = tuple(dict.fromkeys((*parents, 'retained-artifacts')))
        if category == 'build':
            label = 'Reuse retained artifacts' if retained else 'Build & Package'
            description = build_description(platforms, phase_rows, retained)
        else:
            label = operation.label if len(segments) == 1 and category == 'platforms' else labels.get(category, 'Inspection')
            description = operation.description
        nodes.append(replace(operation, id=key, label=label, description=description,
                             dependencies=parents or ('source',), category=category,
                             platforms=platforms, approval_required=category == 'delivery' and any(
                                 phase_effect(phase, plan) in EXTERNAL and getattr(phase, 'approval_required', True)
                                 for phase in phase_rows)))
        members[key] = tuple(keys)
        owners.update(dict.fromkeys(keys, key))
    return replace(grouped, phases=tuple(nodes), members=members, references={}, unassigned=())


def journey_overview(grouped, phases, categories, fallback_platforms, retained):
    """Keep declared journey cards and represent actual build membership in the active map."""
    build_keys = {key for key, category in categories.items() if category == 'build'}
    members = dict(grouped.members)
    references = dict(grouped.references)
    nodes = []
    resolved_dependencies = {}
    card_details = {}
    placed = set()
    for node in grouped.phases:
        key = node.id
        if key.startswith(('prepare.', 'package.')):
            owned = tuple(step for step in members[key] if step in build_keys)
            shared = tuple(step for step in references[key] if step in build_keys)
            if not owned and not shared:
                resolved_dependencies[key] = tuple(dict.fromkeys(parent for dependency in node.dependencies
                    for parent in resolved_dependencies.get(dependency, (dependency,))))
                continue
            placed.update((*owned, *shared))
            platforms = tuple(filter(None, node.platforms)) or fallback_platforms
            description = build_description(platforms, [phases[step] for step in (*owned, *shared)], retained)
            card_details[key] = ('build', '\n'.join(filter(None, (node.description, description))))
            nodes.append(node)
            continue
        members[key] = tuple(step for step in members[key] if step not in build_keys)
        references[key] = tuple(step for step in references[key] if step not in build_keys)
        nodes.append(node)
    unplaced = build_keys - placed
    remaining = tuple(key for key in phases if key in unplaced)
    standalone_build = None
    if remaining or retained and not build_keys:
        # Build work used by tests can precede a platform card. Keep the
        # dedicated card independently rooted at Source and leave the precise
        # success/completion edges available in the task and dependency views.
        platforms = tuple(dict.fromkeys(target for node in grouped.phases
            if unplaced.intersection(grouped.members[node.id] + grouped.references[node.id])
            for target in node.platforms)) or fallback_platforms
        key = 'resolved-build'
        standalone_build = key
        node = ProposedStep(key, 'Reuse retained artifacts' if retained else 'Build & Package',
                            build_description(platforms, [phases[step] for step in remaining], retained),
                            ('source',), platforms=platforms, category='build')
        nodes.insert(1, node)
        members[key] = remaining
        references[key] = ()

    resolved_nodes = []
    for node in nodes:
        dependencies = tuple(dict.fromkeys(parent for key in node.dependencies
                             for parent in resolved_dependencies.get(key, (key,))))
        if standalone_build and node.id.startswith('deliver.') and (
                retained or unplaced.intersection(grouped.members[node.id] + grouped.references[node.id])):
            dependencies = tuple(dict.fromkeys((*dependencies, standalone_build)))
        resolved_nodes.append(replace(node, dependencies=dependencies))
    nodes = tuple(resolved_nodes)
    remaining_tasks = {step for node in nodes for step in members[node.id]}
    # A package sketch may have owned non-build helper phases. Keep every
    # exact task accessible, even when its empty package sketch is removed.
    return ReviewOverview(phases=nodes, members={node.id: members[node.id] for node in nodes},
        references={node.id: references[node.id] for node in nodes},
        unassigned=tuple(key for key in phases if key not in remaining_tasks),
        notes={key: value for key, value in grouped.notes.items() if key not in resolved_dependencies},
        backend=grouped.backend, card_details=card_details)
