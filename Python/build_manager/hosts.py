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


def android_host_issue(system=None, architecture=None):
    """Current manager availability, separate from vendor support and SDK prerequisites.

    This describes the official emulator host binaries, not an Android guest ABI.
    Checking before launching tools avoids accidentally invoking x64 emulation.
    """
    system = system or platform.system()
    architecture = (architecture or platform.machine()).lower()
    supported = {'Darwin': {'arm64', 'aarch64', 'x86_64', 'amd64'},
                 'Linux': {'x86_64', 'amd64'}, 'Windows': {'x86_64', 'amd64'}}
    if system not in supported:
        return 'No supported Android emulator host for ' + system + '.'
    if architecture not in supported[system]:
        return ('Google does not publish a supported Android emulator host binary for '
                + system + ' ' + architecture + '. Select a supported native host; '
                'no architecture, physical-device or remote fallback was selected.')
    if system in {'Linux', 'Windows'}:
        return ('Known limitation: Android emulator testing on ' + system + ' x64 is '
                'unavailable in this manager release. Implementation and native validation '
                'are deferred to the platform follow-up brief. Use macOS for local Android '
                'testing; no fallback was selected automatically.')
    return None


def android_acceleration(system=None):
    system=system or platform.system()
    try:return {'Darwin':'Hypervisor.Framework','Linux':'KVM','Windows':'WHPX'}[system]
    except KeyError:raise ValueError('Unsupported Android host.') from None


def capabilities(targets,*,system=None,architecture=None,ready=(),hosted=(),unavailable=None):
    system=system or platform.system();native={'Darwin':'macos','Linux':'linux','Windows':'windows'}.get(system)
    local={native,'android'} if native else set()
    if system=='Darwin':local.add('ios')
    unavailable=dict(unavailable or {})
    issue=android_host_issue(system,architecture)
    if issue:
        unavailable['android']=issue
    rows=[]
    for target in targets:
        supported=target in local
        if supported and target in unavailable:
            rows.append(Capability(target,'local','unavailable',unavailable[target]))
        else:
            rows.append(Capability(target,'local', 'ready' if supported and target in ready else 'unconfigured' if supported else 'unsupported',
            'Project prerequisites verified.' if supported and target in ready else 'Configure and verify project tools/runtime/acceleration before execution.' if supported else 'This host cannot execute this target locally.'))
        if target in hosted:rows.append(Capability(target,'hosted','unconfigured','Hosted workflow and read/write credentials are configured separately.'))
    return [asdict(row) for row in rows]
