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

    def devices(self, *, timeout=60):
        return json.loads(self.invoke('list', 'devices', '--json', timeout=timeout))

    def create(self, name, device_type, runtime):
        device = self.invoke('create', name, device_type, runtime)
        UUID(device)
        return device

    def boot(self, device, *, name=None):
        UUID(device)
        if name is not None:
            if not isinstance(name, str) or not name or self.matching(device, name, timeout=5) is None:
                raise ValueError('Simulator identity/ownership label is unavailable; refusing boot.')
        try:
            self.invoke('boot', device)
        except subprocess.TimeoutExpired as original:
            if name is None:
                raise
            try:
                self._observe_owned_boot(device, name)
                # Inventory only reconciles the uncertain boot RPC. Readiness
                # still requires the normal command to complete successfully.
                self.invoke('bootstatus', device, '-b', timeout=180)
            except Exception as failure:
                raise original from failure
            return
        try:
            self.invoke('bootstatus', device, '-b', timeout=180)
        except subprocess.TimeoutExpired:
            rows = [row for items in self.devices()['devices'].values()
                    for row in items if row['udid'] == device]
            if (len(rows) != 1 or rows[0]['state'] != 'Booted'
                    or name is not None and rows[0].get('name') != name):
                raise
            # simctl can hang after completing boot. Recheck the exact booted
            # device once, requiring a real successful exit; never reboot it or
            # infer readiness from partial stdout/the inventory state alone.
            self.invoke('bootstatus', device, '-b', timeout=30)

    def _observe_owned_boot(self, device, name):
        deadline = time.monotonic() + 30
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Owned simulator did not reach Booted after its boot RPC timed out.')
            row = self.matching(device, name, timeout=min(5, remaining))
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Owned simulator boot observation exceeded its deadline.')
            if row is None or row['state'] not in ('Booting', 'Booted'):
                raise ValueError('Owned simulator boot state is unverified.')
            if row['state'] == 'Booted':
                return
            time.sleep(min(.2, remaining))

    def matching(self, device, name, *, timeout=60):
        UUID(device)
        rows = [row for items in self.devices(timeout=timeout)['devices'].values() for row in items if row['udid'] == device]
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
