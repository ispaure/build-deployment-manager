"""Reproducible first-boot resources for dedicated test guests."""
import json
import hashlib
import secrets
from pathlib import Path
import shutil
import subprocess
import tarfile
import xml.etree.ElementTree as ET
import urllib.request
import time


DISK_TOOL = '/Applications/Parallels Desktop.app/Contents/MacOS/prl_disk_tool'
WINDOWS_HELPERS = {
    'python-arm64.exe': ('https://www.python.org/ftp/python/3.13.7/python-3.13.7-arm64.exe',
                         'b51bd85374ae87286339cb92e1479710b71d084356419dc3b12fb888599dfa68'),
    'mingit-arm64.zip': ('https://github.com/git-for-windows/git/releases/download/v2.56.0.windows.3/MinGit-2.56.0.3-arm64.zip',
                         '042e7fda964e2072c11435fd0efeb822083c8f5a07c8b00456247bbb5334589d'),
}


def windows_helpers(root):
    """Pinned official installers; never execute or trust an unchecked cache."""
    root = Path(root) / 'media'
    root.mkdir(mode=0o700, exist_ok=True)
    for name, (url, expected) in WINDOWS_HELPERS.items():
        path = root / name
        if path.is_symlink(): raise ValueError('Installer cache cannot be a symlink.')
        if not path.exists():
            partial = path.with_suffix('.partial')
            if partial.exists(): raise ValueError('An interrupted installer download remains: ' + name)
            started, size = time.monotonic(), 0
            try:
                with urllib.request.urlopen(url, timeout=60) as incoming, partial.open('xb') as output:
                    while block := incoming.read(1024 * 1024):
                        size += len(block)
                        if size > 512 * 1024**2 or time.monotonic() - started > 600:
                            raise ValueError('Installer download exceeded its size/time bound.')
                        output.write(block)
                with partial.open('rb') as stream:
                    if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                        raise ValueError('Official installer checksum mismatch: ' + name)
                partial.rename(path)
            finally:
                partial.unlink(missing_ok=True)
        with path.open('rb') as stream:
            if hashlib.file_digest(stream, 'sha256').hexdigest() != expected:
                raise ValueError('Cached official installer checksum mismatch: ' + name)


def import_fedora_disk(image, destination, event=lambda message: None):
    """Convert verified qcow2 to a fresh sparse plain Parallels disk."""
    image, destination = Path(image), Path(destination)
    if destination.exists():
        raise ValueError('Refusing to replace an existing virtual disk.')
    converter = shutil.which('qemu-img')
    if not converter:
        raise ValueError('Install qemu-img to import the Fedora cloud disk.')
    raw = destination.parent / 'fedora-import.raw'
    if raw.exists():
        raise ValueError('Previous disk import remains; inspect it before retrying.')
    event('Converting verified Fedora disk')
    subprocess.run([converter, 'convert', '-O', 'raw', str(image), str(raw)], check=True, timeout=600)
    try:
        subprocess.run([DISK_TOOL, 'create', '--hdd', str(destination), '--size', '64G',
                        '--alloc-policy', 'sparse'], check=True, timeout=120)
        tree = ET.parse(destination / 'DiskDescriptor.xml')
        node = tree.find('./StorageData/Storage/Image')
        name = node.findtext('File') if node is not None else None
        if node is None or node.findtext('Type') != 'Plain' or not name or Path(name).name != name:
            raise ValueError('Unexpected Parallels plain disk descriptor.')
        target = destination / name
        if target.is_symlink() or raw.stat().st_size > target.stat().st_size:
            raise ValueError('Invalid disk import capacity or path.')
        # Preserve sparse zero ranges and the native disk's declared capacity.
        with raw.open('rb') as source, target.open('r+b') as output:
            while block := source.read(4 * 1024 * 1024):
                if block.strip(b'\0'): output.write(block)
                else: output.seek(len(block), 1)
    finally:
        raw.unlink(missing_ok=True)


def fedora_seed(root, uid, *, preserve_host_keys=False):
    """No password login, private per-checkout SSH key, no host-home sharing."""
    root = Path(root)
    key = root / 'linux-ssh'
    if key.is_symlink() or key.with_suffix('.pub').is_symlink():
        raise ValueError('Dedicated SSH key paths cannot be symlinks.')
    if not key.exists():
        subprocess.run(['ssh-keygen', '-q', '-t', 'ed25519', '-N', '', '-f', str(key)], check=True, timeout=30)
    key.chmod(0o600)
    public = key.with_suffix('.pub').read_text().strip()
    if not public.startswith('ssh-ed25519 '): raise ValueError('Invalid dedicated guest public key.')
    folder = root / ('seed-' + uid)
    folder.mkdir(mode=0o700, exist_ok=True)
    config = dict(hostname='bdm-fedora', manage_etc_hosts=True, ssh_pwauth=False,
                  users=[dict(name='manager', lock_passwd=True, shell='/bin/bash', ssh_authorized_keys=[public])],
                  packages=['python3', 'python3-pip', 'git', 'gcc', 'make', 'perl', 'kernel-devel', 'kernel-headers',
                            'xorg-x11-server-Xvfb', 'xauth', 'mesa-libEGL', 'mesa-libGL', 'fontconfig',
                            'dejavu-sans-fonts', 'libxkbcommon-x11', 'xcb-util-cursor'],
                  runcmd=[['sh', '-ec', 'mkdir -p /mnt/bdm-tools; found=0; for d in /dev/sr*; do mount -o ro "$d" /mnt/bdm-tools 2>/dev/null || continue; if test -f /mnt/bdm-tools/install; then /mnt/bdm-tools/install --install-unattended-with-deps; umount /mnt/bdm-tools; found=1; break; fi; umount /mnt/bdm-tools; done; test "$found" = 1; systemctl enable --now sshd; touch /var/lib/cloud/bdm-bootstrap-complete']])
    if preserve_host_keys:
        # Only maintenance of an already initialized owned guest uses this.
        config['ssh_deletekeys'] = False
    (folder / 'user-data').write_text('#cloud-config\n' + json.dumps(config, indent=2))
    (folder / 'meta-data').write_text(json.dumps({'instance-id':uid, 'local-hostname':'bdm-fedora'}))
    seed = root / ('seed-' + uid + '.iso')
    if not seed.exists():
        subprocess.run(['hdiutil', 'makehybrid', '-iso', '-joliet', '-default-volume-name', 'cidata',
                        '-o', str(seed), str(folder)], check=True, timeout=60)
    seed.chmod(0o600)
    return seed


def windows_answer(password):
    """Fresh empty-disk installation only; never used on a reused guest."""
    from xml.sax.saxutils import escape
    password = escape(password)
    header = 'processorArchitecture="arm64" publicKeyToken="31bf3856ad364e35" language="neutral" versionScope="nonSxS"'
    return f'''<?xml version="1.0" encoding="utf-8"?>
<unattend xmlns="urn:schemas-microsoft-com:unattend" xmlns:wcm="http://schemas.microsoft.com/WMIConfig/2002/State">
<settings pass="windowsPE">
<component name="Microsoft-Windows-International-Core-WinPE" {header}><SetupUILanguage><UILanguage>en-US</UILanguage></SetupUILanguage><InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale></component>
<component name="Microsoft-Windows-Setup" {header}>
<DiskConfiguration><Disk wcm:action="add"><DiskID>0</DiskID><WillWipeDisk>true</WillWipeDisk><CreatePartitions>
<CreatePartition wcm:action="add"><Order>1</Order><Type>EFI</Type><Size>260</Size></CreatePartition>
<CreatePartition wcm:action="add"><Order>2</Order><Type>MSR</Type><Size>16</Size></CreatePartition>
<CreatePartition wcm:action="add"><Order>3</Order><Type>Primary</Type><Extend>true</Extend></CreatePartition>
</CreatePartitions><ModifyPartitions><ModifyPartition wcm:action="add"><Order>1</Order><PartitionID>1</PartitionID><Format>FAT32</Format><Label>System</Label></ModifyPartition><ModifyPartition wcm:action="add"><Order>2</Order><PartitionID>3</PartitionID><Format>NTFS</Format><Label>Windows</Label><Letter>C</Letter></ModifyPartition></ModifyPartitions></Disk><WillShowUI>OnError</WillShowUI></DiskConfiguration>
<ImageInstall><OSImage><InstallFrom><MetaData wcm:action="add"><Key>/IMAGE/NAME</Key><Value>Windows 11 Pro</Value></MetaData></InstallFrom><InstallTo><DiskID>0</DiskID><PartitionID>3</PartitionID></InstallTo><WillShowUI>OnError</WillShowUI></OSImage></ImageInstall>
<UserData><AcceptEula>true</AcceptEula><FullName>BDM Test</FullName><Organization>Local testing</Organization><ProductKey><WillShowUI>Never</WillShowUI></ProductKey></UserData></component>
<component name="Microsoft-Windows-PnpCustomizationsWinPE" {header}><DriverPaths><PathAndCredentials wcm:action="add" wcm:keyValue="1"><Path>E:\\Drivers\\virtio_net\\Win10\\ARM64</Path></PathAndCredentials></DriverPaths></component>
</settings>
<settings pass="specialize"><component name="Microsoft-Windows-Shell-Setup" {header}><ComputerName>BDM-Windows</ComputerName><TimeZone>UTC</TimeZone></component></settings>
<settings pass="oobeSystem"><component name="Microsoft-Windows-International-Core" {header}><InputLocale>en-US</InputLocale><SystemLocale>en-US</SystemLocale><UILanguage>en-US</UILanguage><UserLocale>en-US</UserLocale></component>
<component name="Microsoft-Windows-Shell-Setup" {header}>
<OOBE><HideEULAPage>true</HideEULAPage><HideOEMRegistrationScreen>true</HideOEMRegistrationScreen><HideOnlineAccountScreens>true</HideOnlineAccountScreens><HideWirelessSetupInOOBE>true</HideWirelessSetupInOOBE><ProtectYourPC>1</ProtectYourPC></OOBE>
<UserAccounts><LocalAccounts><LocalAccount wcm:action="add"><Name>BDMTest</Name><DisplayName>Build Manager Test</DisplayName><Group>Administrators</Group><Password><Value>{password}</Value><PlainText>true</PlainText></Password></LocalAccount></LocalAccounts></UserAccounts>
<AutoLogon><Username>BDMTest</Username><Enabled>true</Enabled><LogonCount>1</LogonCount><Password><Value>{password}</Value><PlainText>true</PlainText></Password></AutoLogon>
<FirstLogonCommands><SynchronousCommand wcm:action="add"><Order>1</Order><Description>Prepare dedicated test tools</Description><RequiresUserInput>false</RequiresUserInput><CommandLine>powershell.exe -NoProfile -Command "$v=Get-Volume | Where-Object FileSystemLabel -eq 'BDMSETUP'; &amp; ([scriptblock]::Create([IO.File]::ReadAllText(($v.DriveLetter+':\\bootstrap.ps1'))))"</CommandLine></SynchronousCommand></FirstLogonCommands>
</component></settings></unattend>'''


WINDOWS_BOOTSTRAP = r'''$ErrorActionPreference='Stop'
$source=(Get-Volume | Where-Object FileSystemLabel -eq 'BDMSETUP').DriveLetter+':\'
New-Item -ItemType Directory -Force C:\BDM | Out-Null
Start-Transcript C:\BDM\bootstrap.log -Append
try {
 $installer=$source+'python-arm64.exe'
 if((Get-AuthenticodeSignature $installer).Status -ne 'Valid'){throw 'Python installer signature invalid'}
 $p=Start-Process $installer -ArgumentList '/quiet InstallAllUsers=1 PrependPath=1 Include_test=0 Include_launcher=1' -Wait -PassThru
 if($p.ExitCode -notin @(0,3010)){throw 'Python installation failed'}
 Expand-Archive ($source+'mingit-arm64.zip') C:\BDM\Git -Force
 $path=[Environment]::GetEnvironmentVariable('Path','Machine')
 if($path -notlike '*C:\BDM\Git\cmd*'){[Environment]::SetEnvironmentVariable('Path',$path+';C:\BDM\Git\cmd','Machine')}
 $p=Start-Process msiexec.exe -ArgumentList @('/i',('"'+$source+'Tools\Data\ARM64\ParallelsTools-ARM64.msi"'),'/qn','/norestart','/l*v','C:\BDM\tools-install.log') -Wait -PassThru
 if($p.ExitCode -notin @(0,3010)){throw 'Parallels Tools installation failed'}
 'Setup complete; sign in again to refresh PATH.' | Set-Content C:\BDM\bootstrap-complete.txt
} finally { Stop-Transcript }
'''


def windows_seed(root):
    """Bundle reviewed local installers, driver media and a protected test login."""
    root = Path(root)
    windows_helpers(root)
    folder = root / 'windows-seed'
    folder.mkdir(mode=0o700, exist_ok=True)
    credential = root / 'windows-login.json'
    if credential.exists():
        password = json.loads(credential.read_text())['password']
    else:
        from .profiles import save_json
        password = secrets.token_urlsafe(24) + 'aA1!'
        save_json(credential, dict(user='BDMTest', password=password))
    seed = root / 'windows-seed.iso'
    receipt = root / 'windows-seed-checksum.json'
    if seed.exists():
        if seed.is_symlink() or not receipt.is_file():
            raise ValueError('Existing setup media has no ownership checksum; inspect it before reuse.')
        with seed.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
        if json.loads(receipt.read_text()).get('sha256') != digest:
            raise ValueError('Retained Windows setup media changed; refusing automatic recreation.')
        return seed
    for name in ('python-arm64.exe', 'mingit-arm64.zip'):
        shutil.copy2(root / 'media' / name, folder / name)
    with tarfile.open('/Applications/Parallels Desktop.app/Contents/Resources/Tools/prl-tools-win.tar.gz') as stream:
        stream.extractall(folder / 'Tools', filter='data')
    shutil.copytree(folder / 'Tools/Drivers', folder / 'Drivers', dirs_exist_ok=True)
    (folder / 'Autounattend.xml').write_text(windows_answer(password))
    (folder / 'Autounattend.xml').chmod(0o600)
    (folder / 'bootstrap.ps1').write_text(WINDOWS_BOOTSTRAP)
    subprocess.run(['hdiutil', 'makehybrid', '-iso', '-joliet', '-default-volume-name', 'BDMSETUP',
                    '-o', str(seed), str(folder)], check=True, timeout=120)
    seed.chmod(0o600)
    from .profiles import save_json
    with seed.open('rb') as stream:
        save_json(receipt, dict(sha256=hashlib.file_digest(stream, 'sha256').hexdigest()))
    return seed
