"""Simulator lifecycle only; callers supply model/runtime and ownership labels."""
import json
import os
import subprocess
import time
from uuid import UUID


class AppleSimulators:
    def __init__(self, environment=None, *, runner=None):
        self.environment = dict(os.environ, **(environment or {}))
        self.runner = runner or subprocess.run

    def invoke(self, *arguments, timeout=60):
        result = self.runner(['xcrun', 'simctl', *arguments], env=self.environment,
                             capture_output=True, text=True, timeout=timeout)
        if result.returncode:
            from .redaction import Redactor
            raise RuntimeError('Simulator operation failed: ' + Redactor()(result.stderr[-2000:]))
        return result.stdout.strip()

    def toolchain(self):
        values = {}
        for name, argv in [('xcode',['xcodebuild','-version']), ('sdk',['xcrun','--sdk','iphonesimulator','--show-sdk-build-version'])]:
            result = self.runner(argv,env=self.environment,capture_output=True,text=True,timeout=30)
            if result.returncode:
                raise ValueError('Selected Xcode/Simulator SDK is unavailable.')
            values[name] = result.stdout.strip()
        return values

    def devices(self):
        return json.loads(self.invoke('list', 'devices', '--json'))

    def create(self, name, device_type, runtime):
        device = self.invoke('create', name, device_type, runtime)
        UUID(device)
        return device

    def boot(self, device):
        UUID(device)
        self.invoke('boot', device)
        self.invoke('bootstatus', device, '-b', timeout=180)

    def matching(self, device, name):
        UUID(device)
        rows = [row for items in self.devices()['devices'].values() for row in items if row['udid'] == device]
        if not rows:
            return None
        if len(rows) != 1 or rows[0]['name'] != name:
            raise ValueError('Simulator identity/ownership label differs; refusing cleanup.')
        return rows[0]

    def remove(self, device, name):
        row = self.matching(device, name)
        if row is None:
            return
        if row['state'] != 'Shutdown':
            try:
                self.invoke('shutdown', device)
            except RuntimeError:
                # Cancellation can interrupt a previous shutdown between the
                # state read and this request. Verify the same lease again.
                deadline = time.monotonic()+30
                while True:
                    row = self.matching(device, name)
                    if row is None:
                        return
                    if row['state'] == 'Shutdown':
                        break
                    if row['state'] != 'Shutting Down' or time.monotonic() >= deadline:
                        raise
                    time.sleep(.2)
        try:
            self.invoke('delete', device)
        except RuntimeError:
            if self.matching(device, name) is not None:
                raise
