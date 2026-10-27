"""CPython mobile preparation mechanics; callers supply pins, paths and commands.

Cache paths and receipts remain caller-owned. Preparation never selects a project
payload, accepts a device result or installs packages into the host interpreter.
Call preparation serially: upstream compiler tools require a process environment.
"""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

from commonUtils.runtime.streams import file_sha256, stream_signature
from commonUtils.runtime.streams.downloads import DownloadSpec, provision

from .locking import workspace_lock
from .profiles import save_json


def checksum(path):
    return file_sha256(path)


def _download(url, sha256, destination, *, name, version):
    provision(DownloadSpec(name, version, url, sha256, sha256), destination)


def source(cache, pin):
    archive = cache.parent/('cpython-'+pin['revision']+'.tar.gz')
    if not archive.exists():
        _download(pin['archive'], pin['sha256'], archive, name='Pinned CPython archive',
                  version=pin['revision'])
    if checksum(archive)!=pin['sha256']:
        raise ValueError('Pinned CPython cache archive digest differs.')
    if not cache.exists():
        cache.mkdir()
        with tarfile.open(archive) as stream:
            for item in stream:
                item.name = '/'.join(Path(item.name).parts[1:])
                if item.name:
                    stream.extract(item,cache,filter='data')
    # Reject a modified upstream source cache; generated cross-build/testbed
    # output is separate from the archive's immutable source members.
    with tarfile.open(archive) as stream:
        for item in stream:
            relative = Path(*Path(item.name).parts[1:])
            if item.isfile():
                with stream.extractfile(item) as incoming:
                    expected = stream_signature(incoming)[1]
                if not (cache/relative).is_file() or checksum(cache/relative)!=expected:
                    raise ValueError('Pinned CPython source cache changed: '+str(relative))



def runtime_wheels(cache, pins, *, download=False):
    folder = cache/'manager-wheels'
    folder.mkdir(exist_ok=True)
    for pin in pins:
        if Path(pin['filename']).name != pin['filename'] or pin['filename'] in ('', '.', '..'):
            raise ValueError('Runtime wheel filename must be a single filename.')
        path = folder/pin['filename']
        if not path.exists() and download:
            _download(pin['url'], pin['sha256'], path, name='Runtime wheel', version=pin['filename'])
        if not path.is_file() or checksum(path) != pin['sha256']:
            raise ValueError('Prepare the pinned runtime wheel cache before testing: '+pin['filename'])
    return folder



def host_interpreter(cache):
    """Resolve the executable after a build, including macOS's python.exe name."""
    build = Path(cache) / 'cross-build/build'
    return next((path for path in (build / 'python.exe', build / 'python')
                 if path.is_file() and os.access(path, os.X_OK)), None)


def prepare_android(cache, result, pin, *, library_relative, host_configure_args, command,
                    prepare_source, prepare_wheels):
    cache.parent.mkdir(parents=True,exist_ok=True)
    with workspace_lock(cache.parent/'mobile-runtime.lock'):
        prepare_source(cache,pin)
        prepare_wheels(cache, download=True)
        target=pin['android_target']
        host=host_interpreter(cache)
        library=cache/library_relative
        record=cache/'prepared-manager.json'
        if record.exists():
            saved=json.loads(record.read_text())
            if (saved['revision'] == pin['revision'] and saved['archive_sha256'] == pin['sha256']
                    and saved['version'] == pin['version'] and saved['target'] == target
                    and host is not None and library.is_file()
                    and saved['host_sha256'] == checksum(host) and saved['library_sha256'] == checksum(library)):
                result.parent.mkdir(parents=True,exist_ok=True)
                result.write_text(json.dumps(dict(saved,reused=True),indent=2)+'\n')
                return
            raise ValueError('Prepared runtime artifacts changed; inspect the cache before rebuilding.')
        if host is None or not library.is_file():
            previous=dict(os.environ)
            try:
                sdk=subprocess.check_output(['xcrun','--sdk','macosx','--show-sdk-path'],text=True).strip()
                developer=Path(os.environ.get('DEVELOPER_DIR') or subprocess.check_output(['xcode-select','-p'],text=True).strip())
                for link,target_path in [(cache/'macos-sdk',Path(sdk)),(cache/'xcode-toolchain',developer/'Toolchains/XcodeDefault.xctoolchain')]:
                    if not link.exists():link.symlink_to(target_path,target_is_directory=True)
                os.environ.update(SDKROOT=str(cache/'macos-sdk'),CC=str(cache/'xcode-toolchain/usr/bin/clang'),
                    CXX=str(cache/'xcode-toolchain/usr/bin/clang++'),
                    PATH=str(developer/'usr/bin')+os.pathsep+str(cache/'xcode-toolchain/usr/bin')+os.pathsep+os.environ.get('PATH',''))
                command([sys.executable,'Android/android.py','build','build','--',*host_configure_args],cache,1800)
            finally:
                os.environ.clear();os.environ.update(previous)
            command([sys.executable,'Android/android.py','build',pin['android_target']],cache,1800)
        host=host_interpreter(cache)
        if host is None:
            raise RuntimeError('Pinned CPython build produced no executable host interpreter.')
        version=subprocess.check_output([str(host),'-c','import platform;print(platform.python_version())'],text=True,timeout=30).strip()
        if version!=pin['version']:raise ValueError('Pinned CPython host version mismatch.')
        record.write_text(json.dumps(dict(revision=pin['revision'],version=version,target=target,
            host_sha256=checksum(host),library_sha256=checksum(library),archive_sha256=pin['sha256'],status='prepared'),indent=2)+'\n')
        result.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(record,result)


def toolchain():
    return dict(xcode=subprocess.check_output(['xcodebuild', '-version'], text=True).strip(),
                sdk=subprocess.check_output(['xcrun', '--sdk', 'iphonesimulator', '--show-sdk-build-version'], text=True).strip())


def framework(cache, relative):
    return cache / relative


def validate_ios(cache, pin, *, framework_relative, tree_digest, current_toolchain):
    saved = json.loads((cache / 'prepared-manager-ios.json').read_text())
    if (saved['revision'] != pin['revision'] or saved['archive_sha256'] != pin['sha256']
            or saved['toolchain'] != current_toolchain() or not framework(cache, framework_relative).is_dir()
            or saved['framework_sha256'] != tree_digest(framework(cache, framework_relative))):
        raise ValueError('Prepared iOS core runtime differs; inspect the owned cache before rebuilding.')
    return saved


def prepare_ios(cache, result, pin, *, target, framework_relative, host_configure_args,
                command, prepare_source, prepare_wheels, tree_digest, current_toolchain):
    cache.parent.mkdir(parents=True, exist_ok=True)
    with workspace_lock(cache.parent / 'mobile-runtime.lock'):
        prepare_source(cache, pin)
        prepare_wheels(cache, download=True)
        saved = cache / 'prepared-manager-ios.json'
        if saved.exists():
            save_json(result, dict(validate_ios(cache, pin, framework_relative=framework_relative, tree_digest=tree_digest, current_toolchain=current_toolchain), reused=True))
            return
        host = cache / 'cross-build/build/python.exe'
        if not host.exists():
            previous = dict(os.environ)
            try:
                developer = Path(os.environ.get('DEVELOPER_DIR') or subprocess.check_output(['xcode-select', '-p'], text=True).strip())
                sdk = subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip()
                for link, link_target in [(cache / 'macos-sdk', Path(sdk)),
                                     (cache / 'xcode-toolchain', developer / 'Toolchains/XcodeDefault.xctoolchain')]:
                    if link.is_symlink() and link.resolve() != link_target.resolve():
                        raise ValueError('Cached compiler reference changed; inspect before rebuilding.')
                    if not link.exists():
                        link.symlink_to(link_target, target_is_directory=True)
                os.environ.update(SDKROOT=str(cache / 'macos-sdk'), CC=str(cache / 'xcode-toolchain/usr/bin/clang'),
                    CXX=str(cache / 'xcode-toolchain/usr/bin/clang++'),
                    PATH=str(developer / 'usr/bin') + os.pathsep + str(cache / 'xcode-toolchain/usr/bin') + os.pathsep + previous.get('PATH', ''))
                command([sys.executable, 'Apple', 'build', 'iOS', 'build', '--', *host_configure_args], cache, 1800)
            finally:
                os.environ.clear()
                os.environ.update(previous)
        if not host.exists():
            host = cache / 'cross-build/build/python'
        version = subprocess.check_output([str(host), '-c', 'import platform;print(platform.python_version())'], text=True).strip()
        if version != pin['version']:
            raise ValueError('Pinned CPython host version mismatch.')
        command([sys.executable, 'Apple', 'build', 'iOS', target], cache, 2400)
        downloads = cache / 'cross-build/downloads'
        record = dict(status='prepared', revision=pin['revision'], version=version, archive_sha256=pin['sha256'],
            host_sha256=checksum(host), framework_sha256=tree_digest(framework(cache, framework_relative)), toolchain=current_toolchain(),
            dependencies={path.name: checksum(path) for path in downloads.iterdir() if path.is_file()})
        save_json(saved, record)
        save_json(result, record)


