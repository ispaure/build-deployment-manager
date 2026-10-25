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
        started=time.monotonic();waiting=False
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
                if not waiting:event(dict(type='waiting',reason=str(error)));waiting=True
                if (cancelled.is_set() and not cleanup) or time.monotonic()-started>=timeout:
                    raise RuntimeError('Resource wait cancelled or timed out.') from None
                time.sleep(.05)
            except BaseException:
                held.close();raise
        with held:
            yield
