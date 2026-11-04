"""API-1 facade for project adapters. Headless; never imports a project or Qt.

Projects retain dependency pins and policy. Specialized transports are extension
APIs; this facade covers the ordinary descriptor/plan/settings protocol.
"""
import contextlib
import json
import sys

from .models import Phase, Plan
from .profiles import load_profile, save_profile

API_VERSION = 1
__all__ = ["API_VERSION", "Phase", "Plan", "load_profile", "save_profile",
           "operations_for", "backend_options", "validate_capabilities", "serve", "supports"]


def validate_capabilities(capabilities):
    """Validate discovery data before any trusted adapter process is started.

    Empty backend lists deliberately disable a combination. Missing target/host
    mappings retain the API-1 fallback behavior in the resolvers below.
    """
    def labels(value, field, *, empty=False):
        if (not isinstance(value, list) or (not empty and not value)
                or any(not isinstance(item, str) or not item.strip() for item in value)
                or len(set(value)) != len(value)):
            raise ValueError(field + ' must be a list of unique nonempty labels.')

    if not isinstance(capabilities, dict):
        raise ValueError('Project capabilities must be declared as an object.')
    for field in ('platforms', 'operations'):
        labels(capabilities.get(field), 'capabilities.' + field)

    operations = capabilities.get('operations_by_target', {})
    if not isinstance(operations, dict):
        raise ValueError('capabilities.operations_by_target must be an object.')
    for target, choices in operations.items():
        field = 'capabilities.operations_by_target.' + target
        if target not in capabilities['platforms']:
            raise ValueError(field + ' names an undeclared platform.')
        labels(choices, field, empty=True)
        if set(choices) - set(capabilities['operations']):
            raise ValueError(field + ' names an undeclared operation.')

    def backends(mapping, field):
        if not isinstance(mapping, dict):
            raise ValueError(field + ' must be an object.')
        for target, choices in mapping.items():
            location = field + '.' + target
            if target not in capabilities['platforms']:
                raise ValueError(location + ' names an undeclared platform.')
            if isinstance(choices, dict):
                allowed = operations.get(target, capabilities['operations'])
                for operation, values in choices.items():
                    if operation not in allowed:
                        raise ValueError(location + '.' + operation + ' names an unsupported operation.')
                    labels(values, location + '.' + operation, empty=True)
            else:
                labels(choices, location, empty=True)

    backends(capabilities.get('backends', {}), 'capabilities.backends')
    hosts = capabilities.get('host_backends', {})
    if not isinstance(hosts, dict):
        raise ValueError('capabilities.host_backends must be an object.')
    for host, mapping in hosts.items():
        if not isinstance(host, str) or not host.strip():
            raise ValueError('Host backend keys must be nonempty host names.')
        backends(mapping, 'capabilities.host_backends.' + host)


def operations_for(descriptor, target):
    caps = descriptor['capabilities']
    return tuple(caps.get('operations_by_target', {}).get(target, caps['operations']))


def backend_options(descriptor, target, operation='Test', host=None):
    caps = descriptor['capabilities']
    mapping = caps.get('host_backends', {}).get(host or sys.platform, caps.get('backends', {}))
    options = mapping.get(target, ('Local',))
    return tuple(options.get(operation, ()) if isinstance(options, dict) else options)


def serve(handlers, *, stdin=None, stdout=None):
    """Dispatch explicit supported actions; stdout remains a single JSON response.

    Handlers receive (values, context). Context contains checkout-specific profile
    and manager references. No default handler prepares or executes commands.
    """
    request = json.load(stdin or sys.stdin)
    if not isinstance(request, dict) or request.get('schema') != API_VERSION:
        raise ValueError('Unsupported adapter request schema.')
    action = request.get('action')
    if not isinstance(action, str) or action not in handlers:
        raise ValueError('Unsupported adapter action.')
    values = request.get('values', {})
    if not isinstance(values, dict):
        raise ValueError('Adapter values must be an object.')
    from .credentials import reject_secrets
    reject_secrets(values)
    with contextlib.redirect_stdout(sys.stderr):
        result = handlers[action](values, {k: v for k, v in request.items() if k not in {'schema', 'action', 'values'}})
    if isinstance(result, Plan):
        result = result.data()
    json.dump(dict(schema=API_VERSION, result=result), stdout or sys.stdout)
    (stdout or sys.stdout).write('\n')


def supports(project, action):
    """Declared optional actions for bridges, method compatibility for direct adapters."""
    if hasattr(project, 'supports_action'):
        return project.supports_action(action)
    return hasattr(project, {'verification': 'verification_plan', 'tooling_update': 'update_tooling'}.get(action, action))
