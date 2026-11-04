"""Optional retained-input preparation: generic scope, project-owned policy."""
from dataclasses import replace
from pathlib import Path

from .adapter_sdk import supports
from .history import load_run
from .models import Plan
from .run_fields import validate_overrides


def prepare(project, run_directory, destinations, run_overrides=None, *, request=None):
    if not supports(project, 'retained_delivery_plan'):
        raise ValueError('This project does not offer delivery from a saved run.')
    declared = (project.journey_capability or {}).get('destinations', {})
    if (not isinstance(destinations, (list, tuple)) or not destinations
            or any(not isinstance(name, str) or name not in declared for name in destinations)
            or len(set(destinations)) != len(destinations)):
        raise ValueError('Choose distinct project-declared delivery destinations.')
    overrides = validate_overrides(project.run_fields, {} if run_overrides is None else run_overrides)
    directory = Path(run_directory).resolve()
    try:
        previous, report = load_run(directory / 'result.json')
    except (OSError, ValueError) as error:
        raise ValueError('Cannot verify the saved run. Choose another run or rebuild its required artifacts. ' + str(error)) from error
    if report.get('retirement'):
        raise ValueError('This saved run is retired. Prepare a fresh build for delivery.')
    descriptor = project.descriptor
    if previous.project != descriptor['name'] or previous.adapter and (
            previous.adapter.get('project_id') != descriptor['project_id']
            or previous.adapter.get('checkout') != str(project.root)):
        raise ValueError('Choose a saved run from this registered project checkout.')
    callback = request or project.retained_delivery_plan
    value = callback(run_directory=str(directory), destinations=list(destinations), run_overrides=overrides)
    plan = Plan.from_data(value.data() if isinstance(value, Plan) else value)
    if plan.project != descriptor['name']:
        raise ValueError('Prepared delivery belongs to a different project.')
    if Path(plan.workspace).resolve() == Path(previous.workspace).resolve():
        raise ValueError('Retained delivery needs a fresh workspace; preserve the original run.')
    if plan.journey.get('destinations') and set(plan.journey['destinations']) != set(destinations):
        raise ValueError('Prepared delivery destinations differ from the requested selection.')
    if hasattr(project, 'row'):
        plan = replace(plan, adapter=dict(api=1, project_id=descriptor['project_id'],
            descriptor_sha256=project.row['descriptor'], checkout=str(project.root)))
    return plan
