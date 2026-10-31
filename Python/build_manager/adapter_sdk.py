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
           "operations_for", "backend_options", "serve", "supports"]


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
    return hasattr(project, {'verification': 'verification_plan'}.get(action, action))
