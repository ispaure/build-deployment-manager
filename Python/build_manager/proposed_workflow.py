"""Non-executable workflow sketches from UI choices, without adapter calls or I/O."""
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class ProposedStep:
    id: str
    label: str
    description: str
    dependencies: tuple[str, ...] = ()
    section: str = 'platforms'
    target: str = ''
    issue: bool = False
    always: bool = False
    platforms: tuple[str, ...] = ()
    backend: str = ''


@dataclass(frozen=True)
class ChoiceBlocker:
    id: str
    label: str
    section: str
    target: str = ''
    field: str = ''


@dataclass(frozen=True)
class ProposedWorkflow:
    phases: tuple[ProposedStep, ...]
    messages: tuple[str, ...] = ()
    proposed: bool = True
    blockers: tuple[ChoiceBlocker, ...] = ()


def propose(*, capability, goal, revision, platforms, destinations, backends,
            operation='', platform='', backend='', recipients=None, values=None):
    """Summarize intent, never manufacture executable phases or verified readiness."""
    messages = []
    blockers = []
    source = ('Current files · includes edits' if revision == 'working-tree' else
              'Latest commit · excludes edits' if revision == 'HEAD' else
              'Specific revision: ' + revision if revision.strip() else 'Choose a source revision')
    nodes = [ProposedStep('source', 'Source', source, section='source', issue=not revision.strip())]
    if not revision.strip():
        messages.append('Choose a commit, branch or tag in Source.')
        blockers.append(ChoiceBlocker('source', 'Choose source…', 'source'))
    if goal == 'advanced' or not capability:
        nodes.append(ProposedStep('operation', operation or 'Choose an operation',
            ' · '.join(filter(None, (platform, backend))), ('source',), 'platforms',
            platforms=(platform,), backend=backend))
        messages.append('This project defines the operation’s internal steps and effects during Review.')
        return ProposedWorkflow(tuple(nodes), tuple(messages), blockers=tuple(blockers))
    checks = []
    source_requirements = {}
    for target in platforms:
        row = capability['platforms'][target]
        key = 'platform.' + target
        nodes.append(ProposedStep(key, row.get('label', target).split(' (')[0],
            'Required checks · ' + backends.get(target, row['backend']), ('source',), 'platforms', target,
            platforms=(target,), backend=backends.get(target, row['backend'])))
        checks.append(key)
    if not checks:
        nodes.append(ProposedStep('choose-platforms', 'Choose platforms', 'Select at least one platform to test.',
                                  ('source',), 'platforms', issue=True))
        messages.append('Select at least one platform to see its branches.')
        blockers.append(ChoiceBlocker('platforms', 'Choose platforms…', 'platforms'))
    def platform_requirements(targets):
        required = []
        for target in targets:
            key = ('platform.' if target in platforms else 'missing.') + target
            if target not in platforms and not any(node.id == key for node in nodes):
                label = capability['platforms'][target].get('label', target).split(' (')[0]
                nodes.append(ProposedStep(key, 'Select ' + label, 'Required by the selected delivery.',
                                          ('source',), 'platforms', target, True, platforms=(target,)))
                blockers.append(ChoiceBlocker(key, 'Select ' + label + '…', 'platforms', target))
            required.append(key)
        return tuple(required)

    def add_package(key, destination):
        node_id = 'package.' + key
        if any(node.id == node_id for node in nodes):return node_id
        row = capability['packages'][key]
        if row.get('source_policy', 'captured') != 'captured':
            label = capability['destinations'][destination]['label'].split(' · ')[0]
            if source_requirements.get(label) != 'clean-checkout':
                source_requirements[label] = row['source_policy']
        parents = tuple(add_package(parent, destination) for parent in row.get('dependencies', []))
        covered = {target for parent in row.get('dependencies', [])
                   for target in capability['packages'][parent]['platforms']}
        required = platform_requirements([target for target in row['platforms'] if target not in covered])
        nodes.append(ProposedStep(node_id, row['label'], row.get('description', ''),
            tuple(dict.fromkeys((*required, *parents))), 'delivery', destination,
            bool(set(row['platforms']) - set(platforms)), platforms=tuple(row['platforms'])))
        return node_id

    if goal == 'deliver':
        for name in destinations:
            row = capability['destinations'][name]
            if row.get('source_policy', 'captured') != 'captured':
                source_requirements[row['label'].split(' · ')[0]] = row['source_policy']
            from .journeys import destination_package
            required = platform_requirements(row['platforms'])
            missing = set(row['platforms']) - set(platforms)
            if missing:
                messages.append(row['label'] + ' needs: ' + ', '.join(sorted(missing)) + '.')
            label = row['label'].split(' · ')[0]
            package = destination_package(row, values or {})
            if package:
                prepare = add_package(package, name)
            else:
                prepare = 'prepare.' + name
                nodes.append(ProposedStep(prepare, 'Prepare package', label + ' package · project resolves build steps during Review',
                    required or ('choose-platforms',), 'delivery', name, bool(missing), platforms=tuple(row['platforms'])))
            people = (recipients or {}).get(row.get('recipient_field'), [])
            if row.get('recipient_field') and not people:
                blockers.append(ChoiceBlocker('recipients.' + name, 'Choose ' + label + ' recipients…',
                    'delivery', name, row['recipient_field']))
            if row.get('recipient_field') and people:
                for index, person in enumerate(people):
                    nodes.append(ProposedStep('deliver.' + name + '.' + str(index), person,
                        'Review & install on this device', (prepare,), 'delivery', name, bool(missing), platforms=tuple(row['platforms'])))
            else:
                issue = bool(missing) or bool(row.get('recipient_field'))
                nodes.append(ProposedStep('deliver.' + name, label,
                    'Choose devices in Delivery' if row.get('recipient_field') else 'Review & approve before delivery',
                    (prepare,), 'delivery', name, issue, platforms=tuple(row['platforms'])))
        if not destinations:
            nodes.append(ProposedStep('choose-delivery', 'Choose destinations', 'Select where successful builds should go.',
                                      tuple(checks) or ('choose-platforms',), 'delivery', issue=True))
            messages.append('Select a delivery destination, or choose Validate for checks only.')
            blockers.append(ChoiceBlocker('delivery', 'Choose destinations…', 'delivery'))
        for policy in ('committed', 'clean-checkout'):
            names = [name for name, required in source_requirements.items() if required == policy]
            if names:
                messages.append(', '.join(names) + (' requires committed source and a clean checkout. Commit your intended edits or set them aside before release.'
                    if policy == 'clean-checkout' else ' requires committed source. Choose Latest commit to exclude edits, or commit the edits you want to deliver.'))
        if revision == 'working-tree' and not source_requirements:
            messages.append('Delivery policy may require committed source. Latest commit excludes your uncommitted edits.')
    if revision == 'working-tree' and any(backends.get(target) == 'GitHub' for target in platforms):
        messages.append('GitHub checks use committed source. Choose Latest commit or a specific revision to exclude local edits.')
    if revision == 'working-tree' and (source_requirements or any(backends.get(target) == 'GitHub' for target in platforms)):
        blockers.insert(0, ChoiceBlocker('source', 'Choose committed source…', 'source'))
        nodes[0] = replace(nodes[0], issue=True)
    if any(blocker.id.startswith('missing.') for blocker in blockers):
        blockers = [blocker for blocker in blockers if blocker.id != 'platforms']
    return ProposedWorkflow(tuple(nodes), tuple(messages), blockers=tuple(blockers))
