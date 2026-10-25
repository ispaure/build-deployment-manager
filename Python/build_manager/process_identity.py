"""Recheck process creation identity before touching a persistent owned process."""
import os
import signal
import subprocess


def identity(pid):
    pid=int(pid)
    if os.name!='nt':
        result=subprocess.run(['ps','-p',str(pid),'-o','lstart=','-o','command='],capture_output=True,text=True,timeout=10)
        return result.stdout.strip() if result.returncode==0 else None
    import ctypes as c
    from ctypes import wintypes as w
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.GetProcessTimes.argtypes=[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)]
    kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.OpenProcess(0x1000,False,pid)
    if not handle:return None
    try:
        times=[w.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]):raise c.WinError(c.get_last_error())
        return (times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
    finally:kernel.CloseHandle(handle)


def stop_owned(pid,expected,*,token=None):
    pid=int(pid)
    if os.name!='nt':
        current=identity(pid)
        if current is None:return
        if current!=expected or token and token not in current:raise ValueError('Persistent process identity changed; refusing termination.')
        try:os.killpg(pid,signal.SIGTERM)
        except ProcessLookupError:return
        return
    import ctypes as c
    from ctypes import wintypes as w
    kernel=c.WinDLL('kernel32',use_last_error=True)
    kernel.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];kernel.OpenProcess.restype=w.HANDLE
    kernel.GetProcessTimes.argtypes=[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)]
    kernel.TerminateProcess.argtypes=[w.HANDLE,w.UINT];kernel.CloseHandle.argtypes=[w.HANDLE]
    handle=kernel.OpenProcess(0x1000|0x0001,False,pid)
    if not handle:return
    try:
        times=[w.FILETIME() for _ in range(4)]
        if not kernel.GetProcessTimes(handle,*[c.byref(t) for t in times]):raise c.WinError(c.get_last_error())
        actual=(times[0].dwHighDateTime<<32)|times[0].dwLowDateTime
        if actual!=expected:raise ValueError('Persistent process creation identity changed; refusing termination.')
        if not kernel.TerminateProcess(handle,1):raise c.WinError(c.get_last_error())
    finally:kernel.CloseHandle(handle)
