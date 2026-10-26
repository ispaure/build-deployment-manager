"""Host-wide bounded slots acquired in stable order across manager processes."""
from contextlib import contextmanager,ExitStack
import hashlib
from pathlib import Path
import time

from .locking import workspace_lock
from .profiles import load_profile,save_profile
from .registry import config_directory


class Resources:
    def __init__(self,directory=None):
        self.directory=Path(directory) if directory else config_directory()/'resources'

    @contextmanager
    def acquire(self,requirements,capacities,*,cancelled,timeout,event=lambda value:None,cleanup=False):
        started=time.monotonic();last_wait=None
        while True:
            held=ExitStack()
            try:
                for name,amount in sorted(requirements.items()):
                    capacity=capacities.get(name,1)
                    if type(amount) is not int or type(capacity) is not int or not 1<=amount<=capacity<=64:
                        raise ValueError('Invalid resource capacity requirement: '+name)
                    key=hashlib.sha256(name.encode()).hexdigest()
                    with workspace_lock(self.directory/'configuration.lock'):
                        path=self.directory/(key+'.json');saved=load_profile(path)
                        if saved and saved.get('capacity')!=capacity:
                            raise ValueError('Resource capacity changed; explicitly reconcile idle host configuration: '+name)
                        if not saved:save_profile(path,{'capacity':capacity},allowed={'capacity'})
                    acquired=0
                    for slot in range(capacity):
                        try:held.enter_context(workspace_lock(self.directory/f'{key}.{slot}.lock'))
                        except RuntimeError:continue
                        acquired+=1
                        if acquired==amount:break
                    if acquired<amount:raise RuntimeError('Waiting for resource: '+name)
                break
            except RuntimeError as error:
                held.close()
                reason=str(error)
                if reason != last_wait:
                    event(dict(type='waiting',reason=reason,resource=name,amount=amount,capacity=capacity))
                    last_wait=reason
                if (cancelled.is_set() and not cleanup) or time.monotonic()-started>=timeout:
                    raise RuntimeError('Resource wait cancelled or timed out.') from None
                time.sleep(.05)
            except BaseException:
                held.close();raise
        with held:
            yield


def resource_label(name):
    """Make declared resource IDs readable without interpreting project commands."""
    kind, separator, scope = str(name).partition(':')
    label = kind.replace('.', ' ').replace('-', ' ').replace('_', ' ').capitalize()
    return label + (' · ' + scope if separator else '')


def resource_details(plan, key):
    """Declared sharing explains possible waits before a run starts."""
    from .plan_summary import phase_title
    phases = {phase.id: phase for phase in plan.phases}
    lines = []
    for name, amount in phases[key].resources.items():
        lines.append('Shared resource: ' + resource_label(name) +
                     f' ({amount} of {plan.capacities.get(name, 1)} slots)')
        peers = [phase_title(phase) for phase in plan.phases if phase.id != key and name in phase.resources]
        if peers:
            lines.append('Also requested by: ' + ', '.join(peers))
    if lines:
        lines.append('Only steps competing for these resources wait; independent platform work can overlap.')
    return lines
