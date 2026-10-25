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
    def __init__(self, sdk, workspace, *, environment=None):
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
        self.workspace.mkdir(parents=True)
        (self.workspace/'avds').mkdir()
        token = uuid4().hex
        name = 'build-manager-'+token
        # Reserve a free console/ADB pair until immediately before launch.
        selected = None
        for port in range(5580,5680,2):
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
                      workspace=str(self.workspace.resolve()),
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
                        '-no-window','-no-audio','-no-snapshot','-no-boot-anim','-gpu','auto','-accel','on'],
                        env=self.environment,stdout=log,stderr=subprocess.STDOUT,start_new_session=os.name!='nt')
                    self.child = child
                    from .process_identity import identity
                    from .hosts import host_identity
                    record.update(pid=child.pid,process_started=identity(child.pid),host=host_identity())
                    self.marker.write_text(json.dumps(record))
                finally:
                    for sig, handler in previous.items():
                        signal.signal(sig,handler)
                if received:
                    raise KeyboardInterrupt
            deadline = time.monotonic()+240
            while time.monotonic()<deadline:
                if child.poll() is not None:
                    raise RuntimeError('Owned emulator exited before readiness; inspect emulator.log.')
                try:
                    if self.invoke('-s',record['serial'],'shell','getprop','sys.boot_completed',timeout=10)=='1':
                        self.verify(record)
                        return record
                except (OSError,subprocess.SubprocessError,RuntimeError):
                    pass
                time.sleep(1)
            raise RuntimeError('Owned Android emulator did not become ready within four minutes.')
        finally:
            for channel in sockets:channel.close()

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
        except (subprocess.SubprocessError, RuntimeError):
            pass  # Already stopped/startup failed; verify the owned PID below.
        if record.get('pid'):
            from .process_identity import identity,stop_owned
            if self.child is not None:
                try:self.child.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self.child.terminate()
                    try:self.child.wait(timeout=5)
                    except subprocess.TimeoutExpired:self.child.kill();self.child.wait(timeout=5)
            else:
                current=identity(record['pid'])
                if current is not None:
                    expected=record['process_started']
                    # Historical Mac records had only lstart; preserve them but
                    # also require the unique AVD token in the current command.
                    if os.name!='nt' and isinstance(expected,str) and current.startswith(expected) and record['name'] in current:
                        expected=current
                    stop_owned(record['pid'],expected,token=record['name'])
                    deadline=time.monotonic()+5
                    while identity(record['pid']) is not None and time.monotonic()<deadline:time.sleep(.1)
                    if identity(record['pid']) is not None:raise RuntimeError('Owned emulator is still active; AVD files were preserved.')
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
