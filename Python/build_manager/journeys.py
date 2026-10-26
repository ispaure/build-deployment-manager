"""Versioned intent and evidence contracts for project-owned integrated plans."""
import re
from copy import deepcopy
import sys


def for_host(capability, host=None):
    """Resolve an explicitly declared host mapping, never infer another backend."""
    if not capability:
        return capability
    result = deepcopy(capability)
    for row in result['platforms'].values():
        row['backend'] = row.get('backends_by_host', {}).get(host or sys.platform, row['backend'])
    return result


def _identifier(value):
    return isinstance(value, str) and bool(re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', value))


def validate_capability(value, capabilities):
    if value is None:
        return
    if not isinstance(value, dict) or value.get('schema') != 1:
        raise ValueError('Unsupported journey capability schema.')
    platforms, destinations = value.get('platforms'), value.get('destinations', {})
    if type(value.get('selectable_backends',False)) is not bool:
        raise ValueError('Selectable backends must be explicitly enabled or disabled.')
    if not isinstance(platforms, dict) or not platforms or not isinstance(destinations, dict):
        raise ValueError('Journey platforms and destinations must be mappings.')
    for target, row in platforms.items():
        if not _identifier(target) or target not in capabilities['platforms'] or not isinstance(row, dict):
            raise ValueError('Unknown journey platform.')
        if 'label' in row and (not isinstance(row['label'], str) or not row['label']):
            raise ValueError('Journey platform labels must be nonempty text.')
        operation = row.get('operation')
        operations = capabilities.get('operations_by_target', {}).get(target, capabilities['operations'])
        if operation not in operations or not isinstance(row.get('backend'), str) or not row['backend']:
            raise ValueError('Journey platforms need a supported validation operation and execution backend.')
        hosts = row.get('backends_by_host', {})
        if (not isinstance(hosts, dict) or any(host not in {'darwin', 'linux', 'win32'} or
                not isinstance(backend, str) or not backend for host, backend in hosts.items())):
            raise ValueError('Journey host backends need explicit supported host names and nonempty labels.')
    for name, row in destinations.items():
        if (not _identifier(name) or not isinstance(row, dict) or not isinstance(row.get('label'), str)
                or not row['label'] or not isinstance(row.get('platforms'), list) or not row['platforms']
                or any(target not in platforms for target in row['platforms'])
                or len(set(row['platforms'])) != len(row['platforms'])
                or not isinstance(row.get('category', 'Destinations'), str)
                or not isinstance(row.get('recipient_field', ''), str)
                or not isinstance(row.get('description', ''), str)):
            raise ValueError('Journey destinations need unique IDs, labels and declared platforms.')
    metadata = [*platforms.values(), *destinations.values()]
    if isinstance(value.get('packages', {}), dict):metadata.extend(value.get('packages', {}).values())
    for row in metadata:
        if not isinstance(row, dict) or row.get('source_policy', 'captured') not in ('captured', 'committed', 'clean-checkout'):
            raise ValueError('Source policy must be captured, committed or clean-checkout.')
    validate_packages(value)
    unavailable = value.get('unavailable_destinations', [])
    if not isinstance(unavailable, list) or any(not isinstance(row, dict)
            or not isinstance(row.get('label'), str) or not row['label']
            or not isinstance(row.get('reason'), str) or not row['reason'] for row in unavailable):
        raise ValueError('Unavailable destinations need labels and an explanation.')


def validate_packages(value):
    """Validate optional project-owned package sketches as an ordered DAG."""
    packages = value.get('packages', {})
    if not isinstance(packages, dict):raise ValueError('Journey packages must be a mapping.')
    seen = set()
    coverage = {}
    for key, row in packages.items():
        if (not _identifier(key) or not isinstance(row, dict)
                or not isinstance(row.get('label'), str) or not row['label']
                or not isinstance(row.get('description', ''), str)
                or not isinstance(row.get('stage'), str) or row['stage'] not in {'build', 'package'}
                or not isinstance(row.get('platforms'), list) or not row['platforms']
                or any(not isinstance(target, str) or target not in value['platforms'] for target in row['platforms'])
                or not isinstance(row.get('dependencies', []), list)
                or any(not isinstance(parent, str) or parent not in seen for parent in row.get('dependencies', []))):
            raise ValueError('Packages need labels, stages, platforms and preceding package dependencies.')
        seen.add(key)
        coverage[key] = set(row['platforms']).union(*(coverage[parent] for parent in row.get('dependencies', [])))
    for row in value.get('destinations', {}).values():
        variants = row.get('package_variants', {})
        if (not isinstance(variants, dict) or
                any(not isinstance(key, str) or not key or not isinstance(ref, str) or ref not in seen for key, ref in variants.items())
                or (variants and (not isinstance(row.get('package_field'), str) or not row['package_field']
                                  or not isinstance(row.get('package_default'), str) or row['package_default'] not in variants))
                or ('package' in row and (not isinstance(row['package'], str) or row['package'] not in seen))):
            raise ValueError('Destination packages must reference declared packages and variant inputs.')
        for key in ([row['package']] if 'package' in row else list(variants.values())):
            if not coverage[key].issubset(row['platforms']):
                raise ValueError('Destination platforms must include their package prerequisites.')


def destination_package(row, values):
    variants = row.get('package_variants', {})
    return variants.get(values.get(row.get('package_field'), row.get('package_default'))) if variants else row.get('package')


def request(capability, goal, platforms, destinations, *, backends=None):
    if not capability:
        raise ValueError('This project has not declared integrated multi-platform workflows. Use an advanced operation.')
    if goal not in {'validate', 'deliver'} or not platforms or len(set(platforms)) != len(platforms):
        raise ValueError('Choose a goal and at least one distinct platform.')
    if any(target not in capability['platforms'] for target in platforms):
        raise ValueError('Unsupported journey platform.')
    if len(set(destinations)) != len(destinations) or any(name not in capability.get('destinations', {}) for name in destinations):
        raise ValueError('Unsupported delivery destination.')
    if goal == 'validate' and destinations:
        raise ValueError('Validation cannot include delivery actions.')
    if goal == 'deliver' and not destinations:
        raise ValueError('Choose at least one delivery destination.')
    for name in destinations:
        missing = set(capability['destinations'][name]['platforms']) - set(platforms)
        if missing:
            raise ValueError(capability['destinations'][name]['label'] + ' requires: ' + ', '.join(sorted(missing)) +
                             '. Select those platforms or remove this destination.')
    result = dict(schema=1, goal=goal, platforms=list(platforms), destinations=list(destinations))
    if backends is not None:
        if (not isinstance(backends, dict) or set(backends) != set(platforms)
                or any(not isinstance(value, str) or not value for value in backends.values())):
            raise ValueError('Choose an execution location for every selected platform.')
        result['backends'] = dict(backends)
    if destinations:
        result['destination_platforms'] = {name: list(capability['destinations'][name]['platforms']) for name in destinations}
    return result


def validate_plan(plan, intent=None):
    """Reject undeclared effects, missing checks and bypassed destination validation gates."""
    from .workflows import ancestors, EXTERNAL
    data = plan.journey
    if not isinstance(data, dict) or data.get('schema') != 1 or data.get('goal') not in {'validate', 'deliver'}:
        raise ValueError('An integrated plan needs journey evidence schema 1.')
    platforms, destinations = data.get('platforms'), data.get('destinations')
    if not isinstance(platforms, dict) or not platforms or not isinstance(destinations, dict):
        raise ValueError('Journey evidence must map platforms to checks and destinations to effects.')
    if intent and (data['goal'] != intent['goal'] or set(platforms) != set(intent['platforms'])
                   or set(destinations) != set(intent['destinations'])):
        raise ValueError('The prepared plan does not match the selected platforms and destinations.')
    phases = {phase.id: phase for phase in plan.phases}
    gates = set()
    for target, checks in platforms.items():
        if not _identifier(target) or not isinstance(checks, list) or not checks or len(set(checks)) != len(checks):
            raise ValueError('Each platform must declare required validation steps.')
        for step in checks:
            phase = phases.get(step)
            if phase is None or not phase.required or phase.always or phase.kind != 'test' or phase.effect not in {'test', 'inherit'}:
                raise ValueError('Platform validation must reference required test steps.')
            if phase.effect == 'inherit' and plan.effect != 'test':
                raise ValueError('Validation steps cannot inherit an external effect.')
            gates.add(step)
    dispatches = {phase.id for phase in plan.phases if (phase.effect if phase.effect!='inherit' else plan.effect) == 'dispatch'}
    executions = data.get('executions', {})
    if not isinstance(executions, dict):
        raise ValueError('Execution locations must be a mapping.')
    declared_dispatches = set()
    for target, execution in executions.items():
        if (target not in platforms or not isinstance(execution, dict)
                or not isinstance(execution.get('backend'), str) or not execution['backend']
                or not isinstance(execution.get('steps', []), list)):
            raise ValueError('Each execution location must identify its platform, backend and dispatch steps.')
        if intent and intent.get('backends') and execution['backend'] != intent['backends'][target]:
            raise ValueError('Prepared execution location differs from the selected platform host.')
        for step in execution.get('steps', []):
            if (not isinstance(step,str) or step not in dispatches or step in declared_dispatches or phases[step].effect!='dispatch' or phases[step].always
                    or not phases[step].required
                    or not all(step in ancestors(plan, gate) for gate in platforms[target])):
                raise ValueError('Hosted checks must be required, reviewed dispatches upstream of their platform gate.')
            declared_dispatches.add(step)
    if declared_dispatches != dispatches:
        raise ValueError('A hosted test dispatch must belong to a declared platform execution.')
    if intent and intent.get('backends') and set(executions) != set(platforms):
        raise ValueError('Prepared plan is missing selected execution locations.')
    external = {phase.id for phase in plan.phases if (phase.effect if phase.effect != 'inherit' else plan.effect) in EXTERNAL - {'dispatch'}}
    declared = set()
    for name, row in destinations.items():
        if (not _identifier(name) or not isinstance(row, dict) or not isinstance(row.get('identity'), str)
                or not row['identity'].strip() or not isinstance(row.get('steps'), list) or not row['steps']):
            raise ValueError('Each destination needs its exact identity and external steps.')
        required_platforms = row.get('platforms', list(platforms))
        if (not isinstance(required_platforms, list) or not required_platforms
                or any(not isinstance(target, str) or target not in platforms for target in required_platforms)
                or len(set(required_platforms)) != len(required_platforms)):
            raise ValueError('Destination platforms must name selected platforms without duplicates.')
        expected = (intent or {}).get('destination_platforms', {}).get(name, [])
        if not set(expected).issubset(required_platforms):
            raise ValueError('Destination validation omits a platform required by its descriptor.')
        required_gates = {gate for target in required_platforms for gate in platforms[target]}
        for step in row['steps']:
            if step not in external or step in declared:
                raise ValueError('Delivery steps must belong to exactly one selected destination.')
            phase = phases[step]
            if phase.always or phase.effect not in EXTERNAL or not phase.required:
                raise ValueError('Delivery requires explicit reviewed effects on required non-cleanup steps.')
            if not required_gates.issubset(ancestors(plan, step)):
                raise ValueError('Every delivery must depend on its required platform validation gates.')
            declared.add(step)
    if external != declared or (data['goal'] == 'validate' and external) or (data['goal'] == 'deliver' and not destinations):
        raise ValueError('The plan contains unselected delivery actions or is missing selected deliveries.')


def outcomes(plan, rows):
    """Summaries preserve partial success without translating unknown into failure."""
    states = {row['id']: row['status'] for row in rows}
    def group(steps):
        values = [states.get(step, 'queued') for step in steps]
        if all(value == 'passed' for value in values):
            return 'passed'
        for value in ('unknown', 'failed', 'timeout', 'running', 'awaiting_review', 'cancelled', 'skipped', 'queued'):
            if value in values:
                return value
        return 'pending'
    return [(target, group(steps)) for target, steps in plan.journey.get('platforms', {}).items()] + [
        (row['identity'], group(row['steps'])) for row in plan.journey.get('destinations', {}).values()]
