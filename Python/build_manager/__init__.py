"""Project-independent operation planning and execution; no application imports."""

# Standalone tools bind the manager pin. An adapter subprocess explicitly opts
# into its project's interpreter/source roots before loading this library.
import importlib.util
import os
from pathlib import Path
import sys

_source_root = Path(__file__).resolve().parents[1]
if not (_source_root / 'commonUtils' / '__init__.py').is_file():
    raise ImportError('Initialize the pinned Python/commonUtils submodule in the manager Git checkout.')
_context = os.environ.get('BUILD_MANAGER_DEPENDENCIES', 'manager')
if _context == 'project':
    if importlib.util.find_spec('commonUtils') is None:
        raise ImportError('Project commonUtils is unavailable; initialize this project dependency '
                          'and supply its source root before importing build_manager.')
elif _context == 'manager':
    # Preserve legacy consumers that explicitly imported their dependency first.
    # New integrations use project context so both import orders are equivalent.
    if 'commonUtils' not in sys.modules:
        sys.path.insert(0, str(_source_root))
else:
    raise ImportError('BUILD_MANAGER_DEPENDENCIES must be manager or project.')

from .models import Phase, Plan
from .executor import Executor

__all__ = ['Phase', 'Plan', 'Executor']
