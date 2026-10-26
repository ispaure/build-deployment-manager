"""Non-executable workflow sketches from UI choices, without adapter calls or I/O."""
from dataclasses import dataclass


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


@dataclass(frozen=True)
class ProposedWorkflow:
    phases: tuple[ProposedStep, ...]
    messages: tuple[str, ...] = ()
    proposed: bool = True


def propose(*, capability, goal, revision, platforms, destinations, backends,
            operation='', platform='', backend='', recipients=None):
    """Summarize intent, never manufacture executable phases or verified readiness."""
    messages = []
    source = ('Current files · includes edits' if revision == 'working-tree' else
              'Latest commit · excludes edits' if revision == 'HEAD' else
              'Specific revision: ' + revision if revision.strip() else 'Choose a source revision')
    nodes = [ProposedStep('source', 'Source', source, section='source', issue=not revision.strip())]
    if not revision.strip():
        messages.append('Choose a commit, branch or tag in Source.')
    if goal == 'advanced' or not capability:
        nodes.append(ProposedStep('operation', operation or 'Choose an operation',
            ' · '.join(filter(None, (platform, backend))), ('source',), 'platforms'))
        messages.append('This project defines the operation’s internal steps and effects during Review.')
        return ProposedWorkflow(tuple(nodes), tuple(messages))
    checks = []
    for target in platforms:
        row = capability['platforms'][target]
        key = 'platform.' + target
        nodes.append(ProposedStep(key, row.get('label', target).split(' (')[0],
            'Required checks · ' + backends.get(target, row['backend']), ('source',), 'platforms', target))
        checks.append(key)
    if not checks:
        nodes.append(ProposedStep('choose-platforms', 'Choose platforms', 'Select at least one platform to test.',
                                  ('source',), 'platforms', issue=True))
        messages.append('Select at least one platform to see its branches.')
    if goal == 'deliver':
        for name in destinations:
            row = capability['destinations'][name]
            required = ['platform.' + target for target in row['platforms'] if target in platforms]
            for target in row['platforms']:
                if target not in platforms:
                    key = 'missing.' + target
                    if not any(node.id == key for node in nodes):
                        label = capability['platforms'][target].get('label', target).split(' (')[0]
                        nodes.append(ProposedStep(key, 'Select ' + label, 'Required by the selected delivery.',
                                                  ('source',), 'platforms', target, True))
                    required.append(key)
            missing = set(row['platforms']) - set(platforms)
            if missing:
                messages.append(row['label'] + ' needs: ' + ', '.join(sorted(missing)) + '.')
            prepare = 'prepare.' + name
            label = row['label'].split(' · ')[0]
            nodes.append(ProposedStep(prepare, 'Prepare package', label + ' package',
                tuple(required) or ('choose-platforms',), 'delivery', name, bool(missing)))
            people = (recipients or {}).get(row.get('recipient_field'), [])
            if row.get('recipient_field') and people:
                for index, person in enumerate(people):
                    nodes.append(ProposedStep('deliver.' + name + '.' + str(index), person,
                        'Review & install on this device', (prepare,), 'delivery', name, bool(missing)))
            else:
                issue = bool(missing) or bool(row.get('recipient_field'))
                nodes.append(ProposedStep('deliver.' + name, label,
                    'Choose devices in Delivery' if row.get('recipient_field') else 'Review & approve before delivery',
                    (prepare,), 'delivery', name, issue))
        if not destinations:
            nodes.append(ProposedStep('choose-delivery', 'Choose destinations', 'Select where successful builds should go.',
                                      tuple(checks) or ('choose-platforms',), 'delivery', issue=True))
            messages.append('Select a delivery destination, or choose Validate for checks only.')
        if revision == 'working-tree':
            messages.append('Delivery policy may require committed source. Latest commit excludes your uncommitted edits.')
    if revision == 'working-tree' and any(backends.get(target) == 'GitHub' for target in platforms):
        messages.append('GitHub checks use committed source. Choose Latest commit or a specific revision to exclude local edits.')
    return ProposedWorkflow(tuple(nodes), tuple(messages))
