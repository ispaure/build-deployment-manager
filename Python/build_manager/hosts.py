"""Explicit host policy, separate from project and hosted capabilities."""
from dataclasses import asdict,dataclass
import platform
import sys


@dataclass(frozen=True)
class Capability:
    target: str
    location: str
    status: str
    reason: str


def host_identity():
    return dict(system=platform.system(),kernel=platform.release(),architecture=platform.machine(),python=sys.version)


def android_abi(architecture=None):
    architecture=(architecture or platform.machine()).lower()
    if architecture in {'arm64','aarch64'}:return 'arm64-v8a'
    if architecture in {'amd64','x86_64'}:return 'x86_64'
    raise ValueError('No verified Android image architecture for this host: '+architecture)


def android_acceleration(system=None):
    system=system or platform.system()
    try:return {'Darwin':'Hypervisor.Framework','Linux':'KVM','Windows':'WHPX'}[system]
    except KeyError:raise ValueError('Unsupported Android host.') from None


def capabilities(targets,*,system=None,ready=(),hosted=(),unavailable=None):
    system=system or platform.system();native={'Darwin':'macos','Linux':'linux','Windows':'windows'}.get(system)
    local={native,'android'} if native else set()
    if system=='Darwin':local.add('ios')
    unavailable=unavailable or {}
    rows=[]
    for target in targets:
        supported=target in local
        if supported and target in unavailable:
            rows.append(Capability(target,'local','unavailable',unavailable[target]));continue
        rows.append(Capability(target,'local', 'ready' if supported and target in ready else 'unconfigured' if supported else 'unsupported',
            'Project prerequisites verified.' if supported and target in ready else 'Configure and verify project tools/runtime/acceleration before execution.' if supported else 'This host cannot execute this target locally.'))
        if target in hosted:rows.append(Capability(target,'hosted','unconfigured','Hosted workflow and read/write credentials are configured separately.'))
    return [asdict(row) for row in rows]
