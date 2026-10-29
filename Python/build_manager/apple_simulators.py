"""Simulator lifecycle only; callers supply model/runtime and ownership labels."""
import json
import os
import subprocess
import time
from uuid import UUID


def _run_tool(argv, *, env, capture_output, text, timeout):
    """A timeout must not wait forever for a kernel-stuck Apple tool to exit."""
    if not capture_output or not text:
        raise ValueError('Apple tools require captured text output.')
    process = subprocess.Popen(argv, env=env, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, text=True)
    try:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except BaseException:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            try:
                process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                raise RuntimeError(
                    f'Apple tool PID {process.pid} did not exit after its deadline and kill request. '
                    'Outcome is unverified; inspect the macOS host before retrying.') from None
            raise
        return subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
    finally:
        # Popen's context manager waits without a deadline on exit. Close only
        # our pipes here; an unreaped PID remains explicit recovery evidence.
        process.stdout.close()
        process.stderr.close()


class AppleSimulators:
    def __init__(self, environment=None, *, runner=None):
        self.environment = dict(os.environ, **(environment or {}))
        self.runner = runner or _run_tool

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
        try:
            self.invoke('bootstatus', device, '-b', timeout=180)
        except subprocess.TimeoutExpired:
            rows = [row for items in self.devices()['devices'].values()
                    for row in items if row['udid'] == device]
            if len(rows) != 1 or rows[0]['state'] != 'Booted':
                raise
            # simctl can hang after completing boot. Recheck the exact booted
            # device once, requiring a real successful exit; never reboot it or
            # infer readiness from partial stdout/the inventory state alone.
            self.invoke('bootstatus', device, '-b', timeout=30)

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
