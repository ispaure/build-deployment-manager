"""Plain presentation data for a retained plan; no UI or project imports."""
EXTERNAL = {'upload', 'deploy', 'publish', 'dispatch'}


def phase_title(phase):
    return getattr(phase, 'label', '') or phase.id.replace('.', ' · ').replace('_', ' ').replace('-', ' ').capitalize()


def destination_identity(destination, step):
    for key, row in destination.get('recipients', {}).items():
        if step in row['steps']:
            return row.get('label', key) + ' [' + key + ']'
    return destination['identity']


def captured_choices(plan):
    source = plan.source
    identity = source.get('commit') or source.get('fingerprint') or source.get('revision', 'See exact plan')
    label = str(source.get('selection') or 'Captured source')
    if source.get('dirty'):
        label += ' · includes uncommitted changes'
    journey = getattr(plan, 'journey', {})
    executions = journey.get('executions', {})
    platforms = list(journey.get('platforms', {}))
    if platforms:
        hosts = '\n'.join(name + ' · ' + executions.get(name, {}).get('backend', plan.backend) for name in platforms)
    else:
        platform = plan.adapter.get('platform') or plan.settings.get('platform') or source.get('platform')
        hosts = (str(platform) + ' · ' if platform else '') + plan.backend
    goal = plan.operation
    if source.get('release_tag'):
        goal += '\nRelease: ' + str(source['release_tag'])
    return [('Source', label + '\n' + str(identity)), ('Platforms and execution', hosts), ('Goal', goal)]


def summary_rows(plan, fields=()):
    """Keep external gates and their descendants out of the initial work summary."""
    phases = {phase.id: phase for phase in plan.phases}
    deferred = {phase.id for phase in plan.phases
                if (phase.effect if phase.effect != 'inherit' else plan.effect) in EXTERNAL}
    # Dependencies can be represented in any valid order by callers.
    while True:
        more = {phase.id for phase in plan.phases if set(phase.dependencies) & deferred}
        if more <= deferred:
            break
        deferred.update(more)
    groups = {}
    later = []
    labels = {'test': 'Run checks', 'inspect': 'Inspect files', 'build': 'Prepare files',
              'upload': 'Upload', 'deploy': 'Deliver', 'publish': 'Publish', 'dispatch': 'Launch GitHub checks'}
    destinations = getattr(plan, 'journey', {}).get('destinations', {})
    values = plan.source.get('effective_settings', {}).get('values', {})
    overrides = plan.source.get('run_overrides', {})
    # The captured override itself is authoritative when effective values are absent.
    values = {**overrides, **values}
    shared = []
    for field in fields:
        if field['id'] in values and len(set(field.get('destinations', ())) & set(destinations)) != 1:
            shared.append(field['label'] + ': ' + str(values[field['id']]))
    platforms = getattr(plan, 'journey', {}).get('platforms', {})
    for phase in plan.phases:
        effect = phase.effect if phase.effect != 'inherit' else plan.effect
        if phase.id in deferred:
            lines = [labels[effect] + (' · separate approval required' if effect in EXTERNAL and getattr(phase, 'approval_required', True) else ' · after prerequisites')]
            if plan.effect in EXTERNAL and phase.effect == 'inherit':
                lines = [labels[effect] + ' · confirmation before Start']
            for name, destination in destinations.items():
                if phase.id not in destination['steps']:
                    continue
                recipient = next(((key, row) for key, row in destination.get('recipients', {}).items()
                                  if phase.id in row['steps']), None)
                identity = destination_identity(destination, phase.id)
                lines += ['Destination: ' + identity,
                          'Requires platforms: ' + ', '.join(destination.get('platforms', list(getattr(plan, 'journey', {}).get('platforms', {}))))]
                for field in fields:
                    scope = set(field.get('destinations', ())) & set(destinations)
                    if scope == {name} and field['id'] in values:
                        value = values[field['id']]
                        if recipient:
                            import json
                            try:
                                selected = json.loads(value) if isinstance(value, str) else value
                            except ValueError:
                                selected = None
                            if isinstance(selected, list) and recipient[0] in selected:
                                value = identity
                        lines.append(field['label'] + ': ' + str(value))
            if phase.dependencies:
                lines.append('Waits for: ' + ', '.join(phase_title(phases[key]) for key in phase.dependencies))
            later.append(dict(title=phase_title(phase), detail='\n'.join(lines), keys=(phase.id,)))
        else:
            group = 'Cleanup' if phase.always or phase.kind == 'cleanup' else labels[effect]
            targets = [name for name, steps in platforms.items() if phase.id in steps]
            if effect == 'test' and targets and not phase.always:
                group = 'Validate ' + ', '.join(targets)
            groups.setdefault(group, []).append(phase)
    now = []
    for group, members in groups.items():
        keys = {phase.id for phase in members}
        parents = list(dict.fromkeys(key for phase in members for key in phase.dependencies if key not in keys))
        detail = f'{len(members)} execution step' + ('s' if len(members) != 1 else '')
        detail += '\nWaits for: ' + ', '.join(phase_title(phases[key]) for key in parents) if parents else '\nNo prerequisite outside this group'
        if group == 'Cleanup':
            detail += '\nDeclared cleanup can run after failure.'
        now.append(dict(title=group, detail=detail, keys=tuple(phase.id for phase in members)))
    return now, later, shared


def start_scope(plan):
    if plan.effect in EXTERNAL and any(getattr(phase, 'approval_required', True) for phase in plan.phases
            if (phase.effect if phase.effect != 'inherit' else plan.effect) in EXTERNAL):
        return 'Start asks for confirmation of this external operation before running it.'
    effects = {phase.effect if phase.effect != 'inherit' else plan.effect for phase in plan.phases}
    authorized_actions = any(phase.effect in {'upload', 'publish', 'dispatch'}
                             and not getattr(phase, 'approval_required', True) for phase in plan.phases)
    authorized = 'Start authorizes selected Firebase, TestFlight and GitHub actions after their prerequisites pass. ' if authorized_actions else ''
    if any((phase.effect if phase.effect != 'inherit' else plan.effect) in EXTERNAL
           and getattr(phase, 'approval_required', True) for phase in plan.phases):
        return authorized + ('Start runs eligible checks and preparation. '
            + ('Other external actions' if authorized_actions else 'External actions')
            + ' pause for separate approval; their dependent work waits too.')
    if authorized_actions:
        return authorized + 'Start also runs the reviewed checks and preparation.'
    if effects <= {'test', 'inspect'}:
        return 'Start runs the reviewed checks and inspections. No delivery is selected.'
    return 'Start runs the reviewed local work. Dependencies and resource limits determine when each step starts.'
