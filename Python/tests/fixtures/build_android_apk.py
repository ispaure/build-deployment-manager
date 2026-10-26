"""Build an inert APK for disposable-emulator acceptance; no personal signing."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--sdk',type=Path,required=True);parser.add_argument('--java',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();root=args.output.parent;root.mkdir(parents=True,exist_ok=True)
    tools=max((p for p in (args.sdk/'build-tools').iterdir() if p.name.replace('.','').isdigit()),key=lambda p:tuple(map(int,p.name.split('.'))))
    platform=max((p for p in (args.sdk/'platforms').iterdir() if p.name.startswith('android-') and p.name[8:].isdigit()),key=lambda p:int(p.name[8:]))
    manifest=root/'AndroidManifest.xml';manifest.write_text('<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="io.github.ispaure.buildmanager.fixture"><uses-sdk android:minSdkVersion="23" android:targetSdkVersion="36"/><application android:hasCode="false" android:label="Manager acceptance fixture"/></manifest>')
    suffix='.exe' if os.name=='nt' else ''
    env=dict(os.environ,JAVA_HOME=str(args.java),BUILD_MANAGER_FIXTURE_PASSWORD='synthetic-disposable-fixture-only')
    subprocess.run([str(tools/('aapt'+suffix)),'package','-f','-M',str(manifest),'-I',str(platform/'android.jar'),'-F',str(root/'unsigned.apk')],check=True,env=env)
    subprocess.run([str(args.java/('bin/keytool'+suffix)),'-genkeypair','-keystore',str(root/'fixture.jks'),
        '-storepass:env','BUILD_MANAGER_FIXTURE_PASSWORD','-keypass:env','BUILD_MANAGER_FIXTURE_PASSWORD',
        '-alias','fixture','-dname','CN=Disposable manager fixture','-keyalg','RSA','-validity','1'],check=True,env=env)
    signer=tools/('apksigner.bat' if os.name=='nt' else 'apksigner')
    subprocess.run([str(signer),'sign','--ks',str(root/'fixture.jks'),'--ks-pass','env:BUILD_MANAGER_FIXTURE_PASSWORD',
                    '--out',str(args.output),str(root/'unsigned.apk')],check=True,env=env)
    subprocess.run([str(signer),'verify',str(args.output)],check=True,env=env)
    print(json.dumps(dict(apk=str(args.output),sha256=hashlib.sha256(args.output.read_bytes()).hexdigest(),
                         build_tools=tools.name,platform=platform.name)))


if __name__=='__main__':main()
