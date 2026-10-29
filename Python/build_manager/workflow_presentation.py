"""Headless workflow labels, predicted display states and plan descriptions."""

FAILED = {'failed', 'error', 'timeout', 'cancelled', 'interrupted', 'unknown', 'skipped'}
PENDING = {'queued', 'pending', 'planned'}


def duration(seconds):
    if seconds is None:
        return '—'
    return f'{seconds:.2f}s' if seconds < 60 else f'{int(seconds // 60)}m {seconds % 60:.1f}s'


def plan_overview(plan):
    lines = [f'{plan.project} · {plan.operation}', f'Runs on: {plan.backend}',
             f'Workflow effect: {plan.effect}', '', 'Source:']
    if plan.adapter.get('test_suite'):
        lines.insert(3, 'Selected suite: ' + plan.adapter['test_suite'])
    journey = getattr(plan, 'journey', {})
    if journey:
        lines += ['', 'Selected platforms: ' + ', '.join(journey['platforms']),
                  'Each destination requires its declared platform validation; independent branches can proceed separately.',
                  'Delivery pauses for artifact-specific review. Independent approved branches may overlap.',
                  f'At most {plan.max_workers} steps run at once, subject to shared resources.']
        for name, row in journey['destinations'].items():
            required = ', '.join(row.get('platforms', list(journey['platforms'])))
            lines.append('Destination ' + name + ': ' + row['identity'] + ' · requires: ' + required + ' · ' + ', '.join(row['steps']))
    def describe(value, indent='  '):
        rows = []
        for key, item in value.items():
            label = key.replace('_', ' ').capitalize()
            if isinstance(item, dict):
                rows += [indent + label + ':'] + describe(item, indent + '  ')
            else:
                text = ', '.join(str(part) for part in item) if isinstance(item, (list, tuple)) else str(item)
                rows.append(indent + label + ': ' + text)
        return rows or [indent + 'None declared']
    lines += describe(plan.source)
    lines += ['', 'Settings and declared destinations:', *describe(plan.settings),
              '', 'Steps in execution order (dependencies determine overlap):']
    for number, phase in enumerate(plan.phases, 1):
        effect = phase.effect if phase.effect != 'inherit' else plan.effect
        lines += [f'{number}. {phase.id} · {phase.kind} · {effect}',
                  f'   {"Required" if phase.required else "Optional"}; timeout {duration(phase.timeout)}; '
                  f'depends on: {", ".join(phase.dependencies) or "none"}',
                  '   ' + ('External action: explicit review required.' if effect in {'upload', 'deploy', 'publish','dispatch'}
                            else 'Preparation / local execution.')]
    return '\n'.join(lines)


def title(phase):
    return getattr(phase, 'label', '') or phase.id.replace('.', ' · ').replace('_', ' ').replace('-', ' ').capitalize()


def effect_label(phase, plan):
    if getattr(plan, 'proposed', False):
        return phase.description
    if getattr(phase, 'description', ''):
        return phase.description
    if phase.always:
        return 'Cleanup · runs even after a failure' if phase.kind == 'cleanup' else 'Continue after completion · allows prior failure'
    effect = phase.effect if phase.effect != 'inherit' else plan.effect
    if effect == 'deploy' and not getattr(phase, 'approval_required', True):
        return 'Deliver to selected device'
    if effect == 'upload' and not getattr(phase, 'approval_required', True):
        return 'Upload · authorized by Start'
    if effect in {'publish', 'dispatch'} and not getattr(phase, 'approval_required', True):
        return ('Publish' if effect == 'publish' else 'Launch checks') + ' · authorized by Start'
    return {'test': 'Run checks', 'inspect': 'Inspect files', 'build': 'Build / package',
            'upload': 'Upload · approval required', 'deploy': 'Deliver · approval required',
            'publish': 'Publish · approval required', 'dispatch': 'Launch checks · approval required'}[effect]


def stage_label(phase, plan):
    """Presentation groups only: execution order still comes from dependencies."""
    effect = phase.effect if phase.effect != 'inherit' else plan.effect
    if phase.always or phase.kind == 'cleanup':
        return 'Cleanup'
    if getattr(phase, 'section', '') == 'source':
        return 'Source'
    return {'inspect': 'Inspection', 'test': 'Checks', 'build': 'Build / package',
            'upload': 'Delivery / publication', 'deploy': 'Delivery / publication',
            'publish': 'Delivery / publication', 'dispatch': 'Checks'}.get(effect, 'Checks')


def display_states(plan, facts, preview=False):
    """Explain scheduling without turning predicted blocks into execution evidence."""
    states = {}
    for phase in plan.phases:
        fact = facts.get(phase.id, {})
        status = fact.get('status', ('needs_selection' if phase.issue else 'proposed')
            if getattr(plan, 'proposed', False) else 'planned' if preview else 'queued')
        reason = str(fact.get('reason') or fact.get('error') or '')
        blockers = [key for key in phase.dependencies if states[key][0] in FAILED | {'blocked'}]
        if not preview and not phase.always and blockers and (status in PENDING or status.startswith('waiting')):
            status, reason = 'blocked', 'Will not run because a prerequisite did not pass: ' + ', '.join(blockers)
        elif not reason and status in PENDING:
            reason = (('This step waits for its declared prerequisites to finish; it still runs after failure.'
                       if phase.dependencies or getattr(phase, 'waits_for', ()) else
                       'Whole-workflow cleanup waits for owned running work to finish; it still runs after failure.') if phase.always
                      else 'Waits for: ' + ', '.join(phase.dependencies) if phase.dependencies
                      else 'No prerequisites. Scheduling and resources determine when it starts.')
        states[phase.id] = (status, reason)
    return states


def blocking_prerequisite(plan, facts, key):
    """Navigate to recorded failure evidence behind a predicted blocked step."""
    phases = {phase.id: phase for phase in plan.phases}
    states = display_states(plan, facts)
    if key not in phases or states[key][0] not in {'blocked', 'skipped'}:
        return ''
    pending = list(phases[key].dependencies)
    visited = set()
    while pending:
        parent = pending.pop(0)
        if parent in visited:
            continue
        visited.add(parent)
        if states[parent][0] in {'failed', 'error', 'timeout', 'cancelled', 'interrupted', 'unknown'}:
            return parent
        if states[parent][0] in {'blocked', 'skipped'}:
            pending.extend(phases[parent].dependencies)
    return ''


def state_label(status):
    return {'proposed': 'Proposed', 'needs_selection': 'Needs selection',
        'blocked': 'Won’t run · prerequisite failed', 'planned': 'Planned',
        'queued': 'Waiting to start', 'pending': 'Waiting to start',
        'waiting_resource': 'Waiting for shared resource', 'awaiting_review': 'Waiting for approval',
        'retrying': 'Waiting to reconnect',
        'skipped': 'Skipped'}.get(status, status.replace('_', ' ').capitalize())


def step_time(fact, status):
    """Never present a never-started step's synthetic zero as measured runtime."""
    if status in {'queued', 'pending', 'planned', 'blocked', 'skipped', 'waiting_resource'}:
        return 'Not started' if not fact.get('seconds') else duration(fact['seconds'])
    return duration(fact.get('seconds')) if fact.get('seconds') is not None else ''


def timing_duration(seconds):
    """Compact timing labels retain subsecond precision and comparable units."""
    if seconds is None:
        return '—'
    value, unit = (seconds * 1000, 'ms') if 0 < seconds < 1 else (seconds, 's')
    return f'{value:.2f}'.rstrip('0').rstrip('.') + unit

