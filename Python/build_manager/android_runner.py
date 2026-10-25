"""One supervised portable emulator session; preserves personal AVDs and SDKs."""
import argparse
import json
from pathlib import Path
import signal

from .android_emulators import AndroidEmulator
from .hosts import host_identity


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--workspace',type=Path,required=True)
    parser.add_argument('--image');parser.add_argument('--model')
    parser.add_argument('--cleanup-only',action='store_true')
    parser.add_argument('--package',default='io.github.ispaure.buildmanager.fixture')
    parser.add_argument('--apk',type=Path);parser.add_argument('--result',type=Path,required=True)
    args=parser.parse_args()
    def cancelled(*_):raise KeyboardInterrupt
    for sig in (signal.SIGTERM,signal.SIGINT):signal.signal(sig,cancelled)
    client=AndroidEmulator(args.sdk,args.workspace)
    if args.cleanup_only:
        client.cleanup()
        args.result.parent.mkdir(parents=True,exist_ok=True)
        args.result.write_text(json.dumps(dict(status='passed',cleanup='owned state removed or already absent'))+'\n')
        return 0
    if not args.image or not args.model:parser.error('--image and --model are required for a new session')
    report=dict(host=host_identity(),status='running')
    try:
        with client.session(args.image,args.model) as record:
            report.update(device=record,abi=client.invoke('-s',record['serial'],'shell','getprop','ro.product.cpu.abi'))
            if args.apk:
                if not args.apk.is_file():raise ValueError('Harmless test APK fixture is missing.')
                report['install']=client.invoke('-s',record['serial'],'install','-t',str(args.apk),timeout=120)
                import re
                if not re.fullmatch(r'[A-Za-z0-9_.]+',args.package):raise ValueError('Invalid fixture package identifier.')
                report['package']=client.invoke('-s',record['serial'],'shell','pm','path',args.package)
                if not report['package'].startswith('package:'):raise ValueError('Fixture APK was not installed in the owned emulator.')
            report['status']='passed'
    except BaseException as error:
        report.update(status='cancelled' if isinstance(error,KeyboardInterrupt) else 'failed',error=str(error))
        raise
    finally:
        report['cleanup']='removed' if (args.workspace/'removed-lease.json').exists() else 'incomplete'
        args.result.parent.mkdir(parents=True,exist_ok=True);args.result.write_text(json.dumps(report,indent=2)+'\n')
    return 0


if __name__=='__main__':raise SystemExit(main())
