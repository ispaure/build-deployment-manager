"""Automatic console sign-in for the Manager-owned Windows test account."""
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time


TEST_USER = 'BDMTest'


def read_login(root):
    path = Path(root) / 'windows-login.json'
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_size > 4096):
            raise ValueError('The Manager Windows test login must be a protected local file.')
        try:
            data = json.load(stream)
        except (UnicodeError, ValueError):
            raise ValueError('The Manager Windows test login file is invalid.') from None
    if (not isinstance(data, dict) or data.get('user') != TEST_USER
            or not isinstance(data.get('password'), str)
            or not 1 <= len(data['password']) <= 256 or '\x00' in data['password']):
        raise ValueError('The Manager Windows test login file is invalid.')
    return data['password']


# Microsoft documents DefaultPassword as the LSA secret consulted by Winlogon.
# Supply the password over the Parallels request stream or protected setup media.
CONFIGURE = r"""
function Set-BDMTestSignIn([string] $password) {
 $ErrorActionPreference='Stop'
 $account=Get-LocalUser -Name 'BDMTest'
 if (!$account.Enabled -or (Get-CimInstance Win32_ComputerSystem).PartOfDomain) {
  throw 'The dedicated local test account is unavailable.'
 }
 Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;
public static class BdmLogonSecret {
 [StructLayout(LayoutKind.Sequential)]
 struct LsaString {
    public ushort Length, MaximumLength;
    public IntPtr Buffer;
 }
 [StructLayout(LayoutKind.Sequential)]
 struct ObjectAttributes {
    public int Length;
    public IntPtr RootDirectory, ObjectName;
    public int Attributes;
    public IntPtr SecurityDescriptor, SecurityQualityOfService;
 }
 [DllImport("advapi32.dll")] static extern uint LsaOpenPolicy(
    IntPtr system, ref ObjectAttributes attributes, uint access, out IntPtr policy);
 [DllImport("advapi32.dll")] static extern uint LsaStorePrivateData(
    IntPtr policy, ref LsaString key, ref LsaString secret);
 [DllImport("advapi32.dll")] static extern uint LsaNtStatusToWinError(uint status);
 [DllImport("advapi32.dll")] static extern uint LsaClose(IntPtr policy);
 [DllImport("advapi32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
 [return: MarshalAs(UnmanagedType.Bool)]
 static extern bool LogonUser(string user, string domain, string password,
    int logonType, int provider, out IntPtr token);
 [DllImport("kernel32.dll")] static extern bool CloseHandle(IntPtr handle);
 static void Check(uint status) {
    if (status != 0) throw new Win32Exception((int)LsaNtStatusToWinError(status));
 }
 static LsaString Allocate(string value) {
    return new LsaString {
       Length = checked((ushort)(value.Length * 2)),
       MaximumLength = checked((ushort)((value.Length + 1) * 2)),
       Buffer = Marshal.StringToHGlobalUni(value)
    };
 }
 public static void Write(string password) {
    IntPtr token;
    if (!LogonUser("BDMTest", ".", password, 2, 0, out token))
       throw new Win32Exception(Marshal.GetLastWin32Error());
    CloseHandle(token);
    var attributes = new ObjectAttributes { Length = Marshal.SizeOf(typeof(ObjectAttributes)) };
    IntPtr policy;
    Check(LsaOpenPolicy(IntPtr.Zero, ref attributes, 0x20, out policy));
    try {
       var key = Allocate("DefaultPassword");
       try {
          var secret = Allocate(password);
          try { Check(LsaStorePrivateData(policy, ref key, ref secret)); }
          finally { Marshal.ZeroFreeGlobalAllocUnicode(secret.Buffer); }
       }
       finally { Marshal.FreeHGlobal(key.Buffer); }
    }
    finally { LsaClose(policy); }
 }
}
'@
 [BdmLogonSecret]::Write($password)
 $key='HKLM:\SOFTWARE\Microsoft\Windows NT\CurrentVersion\Winlogon'
 Remove-ItemProperty -Path $key -Name DefaultPassword,AutoLogonCount -ErrorAction SilentlyContinue
 Set-ItemProperty -Path $key -Name DefaultUserName -Value 'BDMTest' -Type String
 Set-ItemProperty -Path $key -Name DefaultDomainName -Value $env:COMPUTERNAME -Type String
 Set-ItemProperty -Path $key -Name ForceAutoLogon -Value '1' -Type String
 Set-ItemProperty -Path $key -Name AutoAdminLogon -Value '1' -Type String
}
"""


def session_state(client, uid):
    """Distinguish no user from unavailable guest tools without emitting identities."""
    try:
        row = subprocess.run([client.executable, 'exec', uid, 'query.exe', 'user'],
                             capture_output=True, timeout=10)
    except subprocess.TimeoutExpired:
        return 'unknown'
    # Parallels may return 1 even when quser prints the active console row.
    test_console = rb'^>?\s*BDMTest\s+console\s+\d+\s+Active\b'
    if (row.returncode == 0 and row.stdout.strip()
            or row.returncode == 1 and re.search(test_console, row.stdout, re.MULTILINE | re.IGNORECASE)):
        return 'present'
    if row.returncode == 1 and b'No User exists' in row.stderr + row.stdout:
        return 'empty'
    return 'unknown'


def configure(client, uid, password):
    command = client.powershell_command(uid)
    command.remove('--current-user')
    # Suppress child output even on failure because a PowerShell diagnostic can
    # echo a value supplied to a failed command.
    payload = client.powershell_payload(
        CONFIGURE + '\nSet-BDMTestSignIn ([Text.Encoding]::UTF8.GetString($transportInput))\n'
                    "Write-Output 'configured'", data=password.encode('utf-8'))
    result = subprocess.run(command, input=payload, capture_output=True, timeout=60)
    if result.returncode or result.stdout.strip() != b'configured':
        raise RuntimeError('The owned Windows guest could not configure protected automatic sign-in.')


def wait_for_session(client, uid, timeout, *, accept_empty=False):
    deadline = time.monotonic() + timeout
    while True:
        state = session_state(client, uid)
        if state == 'present' or accept_empty and state == 'empty':
            return state
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return state
        time.sleep(min(2, remaining))
