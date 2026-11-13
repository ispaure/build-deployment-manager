"""Opt-in test worker reservations shared across platforms and manager processes."""
from contextlib import ExitStack
from dataclasses import replace
import hashlib
import os
from pathlib import Path
import re

from .locking import workspace_lock
from .profiles import load_profile, save_profile
from .registry import config_directory

PREFIX = 'test-workers:'
HOST = PREFIX + 'host'
PLATFORM = PREFIX + 'platform:'
ENV_PLATFORM = 'BUILD_MANAGER_TEST_PLATFORM'
ENV_WORKERS = 'BUILD_MANAGER_TEST_WORKERS'
ENV_RESERVED = 'BUILD_MANAGER_RESERVED_TEST_WORKERS'


def resource_directory(directory=None):
    return Path(directory) if directory is not None else config_directory() / 'resources'


def limits(directory=None):
    host = max(1, min(8, (os.cpu_count() or 2) // 2))
    values = load_profile(resource_directory(directory) / 'test-workers.json')
    if not values:
        values = dict(per_platform=min(4, host), host=host)
    validate_limits(values)
    return values


def validate_limits(values):
    if (set(values) != {'per_platform', 'host'}
            or any(type(value) is not int for value in values.values())
            or not 1 <= values['per_platform'] <= 8
            or not values['per_platform'] <= values['host'] <= 64):
        raise ValueError('Choose 1–8 workers per platform and a computer limit at least that large (up to 64).')


def configure(values, directory=None):
    """Reconcile this namespace only, atomically with resource admission while idle."""
    validate_limits(values)
    directory = resource_directory(directory)
    with workspace_lock(directory / 'configuration.lock'), ExitStack() as held:
        unchanged = limits(directory) == values
        profiles = []
        for path in sorted(directory.glob('*.json')):
            if path.name == 'test-workers.json':
                continue
            saved = load_profile(path)
            name = saved.get('name', '')
            if not isinstance(name, str):
                raise ValueError('Invalid resource name.')
            if name == HOST or name.startswith(PLATFORM):
                if path.stem != hashlib.sha256(name.encode()).hexdigest():
                    raise ValueError('Invalid test worker resource identity.')
                profiles.append((path, name))
                unchanged = unchanged and saved.get('capacity') == values['host' if name == HOST else 'per_platform']
        if unchanged:
            return
        for path, name in profiles:
            for slot in range(64):
                try:
                    held.enter_context(workspace_lock(directory / f'{path.stem}.{slot}.lock'))
                except RuntimeError:
                    raise ValueError('Test workers are active. Save worker limits after those tests finish.') from None
        for path, name in profiles:
            save_profile(path, dict(name=name, capacity=values['host' if name == HOST else 'per_platform']),
                         allowed={'name', 'capacity'})
        save_profile(directory / 'test-workers.json', values, allowed={'per_platform', 'host'})


def reserve(plan, platform, selected, *, accelerated=(), directory=None):
    """Projects select local test phases and explicitly opt audited runners into N workers."""
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,63}', platform):
        raise ValueError('A worker budget needs a stable platform ID.')
    selected, accelerated = set(selected), set(accelerated)
    if not accelerated <= selected or not selected <= {phase.id for phase in plan.phases}:
        raise ValueError('Unknown test worker phase.')
    if not selected:
        return plan
    values = limits(directory)
    key = PLATFORM + platform
    capacities = dict(plan.capacities)
    for name, capacity in ((HOST, values['host']), (key, values['per_platform'])):
        if name in capacities and capacities[name] != capacity or name in plan.resources:
            raise ValueError('Test worker capacity conflicts with the existing plan.')
        capacities[name] = capacity
    phases = []
    for phase in plan.phases:
        if phase.id in selected:
            if phase.kind != 'test' or phase.always or phase.effect not in {'inherit', 'test'}:
                raise ValueError('Only ordinary local test phases may reserve test workers.')
            count = values['per_platform'] if phase.id in accelerated else 1
            phase = replace(phase, resources=dict(phase.resources, **{HOST: count, key: count}),
                            environment=dict(phase.environment, **{ENV_PLATFORM: platform, ENV_WORKERS: str(count)}))
        phases.append(phase)
    return replace(plan, phases=tuple(phases), capacities=capacities)


def admitted_environment(phase, plan, directory):
    """Called under the admission lock; retained plans cannot override newer host limits."""
    environment = dict(phase.environment)
    environment.pop(ENV_RESERVED, None)
    platform = environment.get(ENV_PLATFORM)
    declared = {name for name in phase.resources if name.startswith(PREFIX)}
    if not platform:
        if declared or ENV_WORKERS in environment:
            raise ValueError('Test workers require declared platform and host reservations.')
        return environment
    key = PLATFORM + platform
    values = limits(directory)
    try:
        count = int(environment[ENV_WORKERS])
    except (KeyError, ValueError):
        raise ValueError('Invalid test worker reservation.') from None
    if (declared != {HOST, key} or not 1 <= count <= values['per_platform']
            or phase.resources.get(HOST) != count or phase.resources.get(key) != count
            or plan.capacities.get(HOST) != values['host'] or plan.capacities.get(key) != values['per_platform']):
        raise ValueError('Test worker limits changed or the reservation is incomplete; prepare a new plan.')
    environment[ENV_RESERVED] = str(count)
    return environment
