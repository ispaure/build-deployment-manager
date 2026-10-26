"""Project-independent operation planning and execution; no application imports."""

# Editable console entry points can start outside Python/. Resolve exactly this
# checkout's source root, as the GUI launcher does, before importing commonUtils.
from pathlib import Path
import sys

_source_root = Path(__file__).resolve().parents[1]
if not (_source_root / 'commonUtils' / '__init__.py').is_file():
    raise ImportError('Initialize the pinned Python/commonUtils submodule in the manager Git checkout.')
sys.path.insert(0, str(_source_root))

from .models import Phase, Plan
from .executor import Executor

__all__ = ['Phase', 'Plan', 'Executor']
