"""Owned disposable Android AVD lifecycle; no application/package policy."""
import json
from contextlib import contextmanager
import re
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import time
from uuid import uuid4


class AndroidEmulator:
    def __init__(self, sdk, workspace, *, environment=None, startup_timeout=240, gpu='auto'):
        if type(startup_timeout) is not int or not 1 <= startup_timeout <= 3600:
            raise ValueError('Emulator startup timeout must be 1 to 3600 seconds.')
        if gpu not in {'auto', 'host', 'swiftshader'}:
            raise ValueError('Choose auto, host or swiftshader emulator graphics.')
        self.gpu = gpu
        self.startup_timeout = startup_timeout
        self.sdk, self.workspace = Path(sdk), Path(workspace)
        self.environment = dict(os.environ, **(environment or {}))
        self.environment.update(ANDROID_HOME=str(self.sdk), ANDROID_SDK_ROOT=str(self.sdk),
            ANDROID_USER_HOME=str(self.workspace/'user'), ANDROID_AVD_HOME=str(self.workspace/'avds'))
        suffix = '.exe' if os.name == 'nt' else ''
        self.adb = self.sdk/('platform-tools/adb'+suffix)
        self.emulator = self.sdk/('emulator/emulator'+suffix)
        self.avdmanager = self.sdk/('cmdline-tools/latest/bin/avdmanager'+('.bat' if os.name=='nt' else ''))
        self.child = None
        self.marker = self.workspace/'lease.json'

    def invoke(self, *arguments, timeout=30):
        try:
            return subprocess.check_output([str(self.adb), *arguments], env=self.environment, text=True,
                                           stderr=subprocess.STDOUT, timeout=timeout).strip()
        except subprocess.CalledProcessError as error:
            from .redaction import Redactor
            raise RuntimeError('ADB command failed: '+Redactor()(error.output[-3000:])) from None

    def inspect(self, image, *, acceleration=None):
        if not re.fullmatch(r'system-images;android-\d+;[A-Za-z0-9_]+;(?:arm64-v8a|x86_64)',image):
            raise ValueError('Choose an explicit supported SDK system image identifier.')
        from .hosts import android_host_issue
        issue = android_host_issue()
        if issue:
            raise ValueError(issue)
        required = [self.adb, self.emulator, self.avdmanager,
                    self.sdk/'system-images'/Path(*image.split(';')[1:])/'system.img',
                    self.sdk/'system-images'/Path(*image.split(';')[1:])/'source.properties']
        if any(not path.is_file() for path in required):
            raise ValueError('Selected SDK lacks the required emulator, AVD tools or complete system image.')
        output = subprocess.check_output([str(self.emulator),'-accel-check'], env=self.environment,
                                         text=True, stderr=subprocess.STDOUT, timeout=30)
        from .hosts import android_abi,android_acceleration
        if image.rsplit(';',1)[-1] != android_abi():
            raise ValueError('Selected image is not native to the detected host architecture; no emulation fallback was selected.')
        acceleration = acceleration or android_acceleration()
        if acceleration and acceleration not in output:
            raise ValueError('The selected emulator does not provide required acceleration: '+acceleration)
        return output.strip()

    def start(self, image, model):
        if self.workspace.exists():
            raise ValueError('Select a fresh owned emulator workspace.')
        self.inspect(image)
        from .locking import workspace_lock
        from .registry import config_directory
        # Keep only port allocation/console binding atomic. Guest boots may
        # overlap after the unique console name and bound port are verified.
        with workspace_lock(config_directory() / 'locks/android-emulator-ports.lock', timeout=600):
            record = self._launch(image, model)
        return self._wait_ready(record)

    def _launch(self, image, model):
        if self.workspace.exists():
            raise ValueError('Select a fresh owned emulator workspace.')
        self.inspect(image)
        self.workspace.mkdir(parents=True)
        (self.workspace/'avds').mkdir()
        token = uuid4().hex
        name = 'build-manager-'+token
        # Reserve a free console/ADB pair until immediately before launch.
        selected = None
        advertised = set(re.findall(r'^emulator-(\d+)\s', self.invoke('devices'), re.MULTILINE))
        # The SDK documents even console ports 5554–5584; ADB uses port + 1.
        for port in range(5554,5586,2):
            if str(port) in advertised:
                continue
            sockets = [socket.socket(),socket.socket()]
            try:
                for channel, candidate in zip(sockets,(port,port+1)):
                    channel.bind(('127.0.0.1',candidate))
                selected = (port,sockets)
                break
            except OSError:
                for channel in sockets:channel.close()
        if selected is None:
            raise RuntimeError('No unused emulator console/ADB port pair is available.')
        port,sockets = selected
        record = dict(token=token,name=name,serial='emulator-'+str(port),image=image,model=model,
                      workspace=str(self.workspace.resolve()),gpu=self.gpu,startup_timeout=self.startup_timeout,
                      image_properties=(self.sdk/'system-images'/Path(*image.split(';')[1:])/'source.properties').read_text())
        self.marker.write_text(json.dumps(record))
        try:
            subprocess.run([str(self.avdmanager),'create','avd','--name',name,
                '--package',image,'--device',model], input='no\n', env=self.environment,
                text=True, check=True, timeout=90)
            for channel in sockets:channel.close()
            with (self.workspace/'emulator.log').open('w') as log:
                received = []
                previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT,signal.SIGTERM)}
                for sig in previous:
                    signal.signal(sig, lambda number, frame: received.append(number))
                try:
                    child = subprocess.Popen([str(self.emulator),'-avd',name,'-port',str(port),
                        '-no-window','-no-audio','-no-snapshot','-no-boot-anim','-gpu',self.gpu,'-accel','on'],
                        env=self.environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=os.name!='nt')
                    self.child = child
                    from .process_identity import read_process_fingerprint
                    from .hosts import host_identity
                    record.update(pid=child.pid,process_started=read_process_fingerprint(child.pid),host=host_identity())
                    self.marker.write_text(json.dumps(record))
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig,handler)
                if received:
                    raise KeyboardInterrupt
            deadline = time.monotonic()+60
            while time.monotonic()<deadline:
                if child.poll() is not None:
                    raise RuntimeError(self.startup_failure())
                try:
                    self.verify(record)
                    return record
                except (OSError,subprocess.SubprocessError,RuntimeError,ValueError):
                    time.sleep(.2)
            raise RuntimeError('Owned emulator console did not register within 60 seconds.')
        finally:
            for channel in sockets:channel.close()

    def _wait_ready(self, record):
        from .process_identity import read_process_fingerprint
        child, name = self.child, record['name']
        deadline = time.monotonic()+self.startup_timeout
        while time.monotonic()<deadline:
            if child.poll() is not None:
                raise RuntimeError(self.startup_failure())
            try:
                if self.invoke('-s',record['serial'],'shell','getprop','sys.boot_completed',timeout=10)=='1':
                    self.verify(record)
                    # The emulator launcher may exec its QEMU backend. Capture
                    # the ready command only after checking the same creation
                    # time and the unique AVD identity, never just its PID.
                    ready_fingerprint = read_process_fingerprint(child.pid)
                    initial_fingerprint = record['process_started']
                    if os.name != 'nt':
                        if (not ready_fingerprint or not initial_fingerprint
                                or ready_fingerprint.split()[:5] != initial_fingerprint.split()[:5]
                                or name not in ready_fingerprint):
                            raise RuntimeError('Owned emulator creation identity changed during startup.')
                    elif ready_fingerprint != initial_fingerprint:
                        raise RuntimeError('Owned emulator creation identity changed during startup.')
                    record['process_started'] = ready_fingerprint
                    self.marker.write_text(json.dumps(record))
                    return record
            except (OSError,subprocess.SubprocessError,RuntimeError):
                pass
            time.sleep(1)
        raise RuntimeError(f'Owned Android emulator did not become ready within {self.startup_timeout} seconds.')

    def startup_failure(self):
        """Carry the native startup cause into CLI results before scratch cleanup."""
        path = self.workspace / 'emulator.log'
        try:
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - 8192))
                tail = stream.read(8192).decode('utf-8', errors='replace')
        except OSError:
            tail = ''
        if 'Not enough space to create userdata partition' in tail:
            available = re.search(r'Available: ([0-9.]+ MB)', tail)
            needed = re.search(r'need ([0-9.]+ MB)', tail)
            sizes = (' Available: ' + available.group(1) + '; required: ' + needed.group(1) + '.') if available and needed else ''
            return ('Owned emulator could not allocate its user-data partition.' + sizes
                    + ' Free disk space; review project-owned outputs with build-manager storage. '
                    + 'The manager never deletes system backups or personal files automatically.')
        return 'Owned emulator exited before readiness; inspect emulator.log.'

    def verify(self, record):
        if (record['name']!='build-manager-'+record['token'] or not record['serial'].startswith('emulator-')
                or record['workspace']!=str(self.workspace.resolve())):
            raise ValueError('Owned emulator identity mismatch.')
        lines = self.invoke('-s',record['serial'],'emu','avd','name').splitlines()
        if not lines or lines[0].strip()!=record['name']:
            raise ValueError('ADB serial belongs to another emulator; refusing device actions.')

    def cleanup(self):
        if not self.marker.exists():
            return
        record = json.loads(self.marker.read_text())
        if record['workspace']!=str(self.workspace.resolve()) or record['name']!='build-manager-'+record['token']:
            raise ValueError('Emulator workspace ownership mismatch.')
        try:
            self.verify(record)
            self.invoke('-s',record['serial'],'emu','kill')
            # A successful console shutdown can briefly leave a defunct process
            # whose command no longer contains its AVD token. Wait for it to
            # disappear before considering a creation-checked signal fallback.
            if record.get('pid') and self.child is None:
                from .process_identity import read_process_fingerprint
                deadline = time.monotonic()+5
                while read_process_fingerprint(record['pid']) is not None and time.monotonic()<deadline:
                    time.sleep(.1)
        except ValueError:
            # Never send console commands to a serial owned by another AVD.
            # A recorded process can still be retired by creation identity below.
            if not record.get('pid'):
                raise
        except (subprocess.SubprocessError, RuntimeError):
            pass  # Already stopped/startup failed; verify the owned PID below.
        if record.get('pid'):
            from .process_identity import read_process_fingerprint, stop_owned_process
            if self.child is not None:
                try:self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.child.terminate()
                    try:self.child.wait(timeout=5)
                    except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
            else:
                current=read_process_fingerprint(record['pid'])
                if current is not None:
                    expected_fingerprint=record['process_started']
                    # Historical Mac records had only lstart; preserve them but
                    # also require the unique AVD token in the current command.
                    if os.name!='nt' and isinstance(expected_fingerprint,str) and current.split()[:5] == expected_fingerprint.split()[:5] and record['name'] in current:
                        expected_fingerprint=current
                    stop_owned_process(record['pid'],expected_fingerprint,token=record['name'])
                    deadline=time.monotonic()+5
                    while read_process_fingerprint(record['pid']) is not None and time.monotonic()<deadline:time.sleep(.1)
                    if read_process_fingerprint(record['pid']) is not None:raise RuntimeError('Owned emulator is still active; AVD files were preserved.')
        # Preserve emulator.log and the completed lease as evidence; remove only
        # this operation's disposable AVD and its synthetic user state.
        for name in ('avds','user'):
            path = self.workspace/name
            if path.is_symlink():raise ValueError('Owned AVD workspace was replaced by a link.')
            if path.exists():shutil.rmtree(path)
        self.marker.rename(self.workspace/'removed-lease.json')

    @contextmanager
    def session(self,image,model):
        try:
            yield self.start(image,model)
        finally:
            self.cleanup()
