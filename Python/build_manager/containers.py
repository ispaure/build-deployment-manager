"""Rootless Podman commands and exact owned-container cleanup, with no app policy."""
from pathlib import PurePosixPath


class RootlessContainer:
    def __init__(self, cache, uid, name, image):
        root = PurePosixPath(cache)
        if not root.is_absolute() or uid <= 0 or not name.startswith('build-manager-'):
            raise ValueError('Use an absolute cache, normal user and an owned container name.')
        self.name, self.image = name, image
        self.environment = dict(XDG_RUNTIME_DIR=str(root/'runtime'), XDG_CONFIG_HOME=str(root/'config'))
        self.command = ['podman', '--root', str(root/'storage'), '--runroot', str(root/'run'), '--cgroup-manager', 'cgroupfs']
        self.uid = uid

    def run(self, workspace, argv):
        return [*self.command, 'run', '--rm', '--name', self.name, '--label', 'build-manager.owner='+self.name,
                '--userns=keep-id', '--user', f'{self.uid}:{self.uid}', '--volume', workspace+':'+workspace+':rw',
                '--workdir', workspace+'/source', self.image, *argv]

    def cleanup_script(self):
        # The random name alone is insufficient: verify our ownership label too.
        return '''import json,subprocess,sys
command=json.loads(sys.argv[1]); name=sys.argv[2]
r=subprocess.run(command+['container','inspect',name],capture_output=True,text=True)
if r.returncode:
 if subprocess.run(command+['container','exists',name]).returncode==1: raise SystemExit(0)
 raise RuntimeError('Cannot verify owned container state')
rows=json.loads(r.stdout)
if len(rows)!=1 or rows[0].get('Config',{}).get('Labels',{}).get('build-manager.owner')!=name: raise ValueError('Container ownership mismatch')
subprocess.run(command+['rm','--force',name],check=True,timeout=30)
'''
