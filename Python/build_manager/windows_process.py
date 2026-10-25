"""Race-free Windows child ownership using a job before the first thread runs.

Only the selected phase joins this job, never the embedding UI/application.
The job is closed with kill-on-close, including children after their parent exits.
"""
import ctypes as c
from ctypes import wintypes as w
import os
import subprocess


class Security(c.Structure):
    _fields_ = [('length', w.DWORD), ('descriptor', w.LPVOID), ('inherit', w.BOOL)]


class Startup(c.Structure):
    _fields_ = [('cb', w.DWORD), ('reserved', w.LPWSTR), ('desktop', w.LPWSTR), ('title', w.LPWSTR),
                ('x', w.DWORD), ('y', w.DWORD), ('width', w.DWORD), ('height', w.DWORD),
                ('chars_x', w.DWORD), ('chars_y', w.DWORD), ('fill', w.DWORD), ('flags', w.DWORD),
                ('show', w.WORD), ('reserved_size', w.WORD), ('reserved_bytes', w.LPVOID),
                ('stdin', w.HANDLE), ('stdout', w.HANDLE), ('stderr', w.HANDLE)]


class StartupEx(c.Structure):
    _fields_ = [('startup', Startup), ('attributes', w.LPVOID)]


class ProcessInfo(c.Structure):
    _fields_ = [('process', w.HANDLE), ('thread', w.HANDLE), ('pid', w.DWORD), ('tid', w.DWORD)]


class Limits(c.Structure):
    _fields_ = [('process_time', c.c_int64), ('job_time', c.c_int64), ('flags', w.DWORD),
                ('working_min', c.c_size_t), ('working_max', c.c_size_t), ('active', w.DWORD),
                ('affinity', c.c_size_t), ('priority', w.DWORD), ('scheduling', w.DWORD)]


class ExtendedLimits(c.Structure):
    _fields_ = [('basic', Limits), ('io', c.c_uint64 * 6), ('process_memory', c.c_size_t),
                ('job_memory', c.c_size_t), ('peak_process', c.c_size_t), ('peak_job', c.c_size_t)]


class WindowsProcess:
    def __init__(self, argv, *, cwd, env):
        if os.name != 'nt':
            raise RuntimeError('Windows process ownership requires Windows.')
        import msvcrt
        self.args, self.returncode = list(argv), None
        self.kernel = k = c.WinDLL('kernel32', use_last_error=True)
        declarations = {
            'CreateJobObjectW': ([w.LPVOID, w.LPCWSTR], w.HANDLE),
            'SetInformationJobObject': ([w.HANDLE, c.c_int, w.LPVOID, w.DWORD], w.BOOL),
            'AssignProcessToJobObject': ([w.HANDLE, w.HANDLE], w.BOOL),
            'TerminateJobObject': ([w.HANDLE, w.UINT], w.BOOL),
            'CreatePipe': ([c.POINTER(w.HANDLE), c.POINTER(w.HANDLE), c.POINTER(Security), w.DWORD], w.BOOL),
            'SetHandleInformation': ([w.HANDLE, w.DWORD, w.DWORD], w.BOOL),
            'CreateFileW': ([w.LPCWSTR, w.DWORD, w.DWORD, c.POINTER(Security), w.DWORD, w.DWORD, w.HANDLE], w.HANDLE),
            'InitializeProcThreadAttributeList': ([w.LPVOID, w.DWORD, w.DWORD, c.POINTER(c.c_size_t)], w.BOOL),
            'UpdateProcThreadAttribute': ([w.LPVOID, w.DWORD, c.c_size_t, w.LPVOID, c.c_size_t, w.LPVOID, w.LPVOID], w.BOOL),
            'DeleteProcThreadAttributeList': ([w.LPVOID], None),
            'CreateProcessW': ([w.LPCWSTR, w.LPWSTR, w.LPVOID, w.LPVOID, w.BOOL, w.DWORD,
                                w.LPVOID, w.LPCWSTR, w.LPVOID, c.POINTER(ProcessInfo)], w.BOOL),
            'ResumeThread': ([w.HANDLE], w.DWORD),
            'TerminateProcess': ([w.HANDLE, w.UINT], w.BOOL),
            'WaitForSingleObject': ([w.HANDLE, w.DWORD], w.DWORD),
            'GetExitCodeProcess': ([w.HANDLE, c.POINTER(w.DWORD)], w.BOOL),
            'CloseHandle': ([w.HANDLE], w.BOOL),
        }
        for name, (arguments, result) in declarations.items():
            function = getattr(k, name)
            function.argtypes, function.restype = arguments, result
        self._job = self._process = None
        reader, writer = w.HANDLE(), w.HANDLE()
        null = None
        attributes = None
        information = ProcessInfo()
        success = False
        try:
            self._job = k.CreateJobObjectW(None, None)
            self.check(self._job)
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            self.check(k.SetInformationJobObject(self._job, 9, c.byref(limits), c.sizeof(limits)))
            security = Security(c.sizeof(Security), None, True)
            self.check(k.CreatePipe(c.byref(reader), c.byref(writer), c.byref(security), 0))
            self.check(k.SetHandleInformation(reader, 1, 0))
            null = k.CreateFileW('NUL', 0x80000000, 3, c.byref(security), 3, 0, None)
            if null == c.c_void_p(-1).value:
                raise c.WinError(c.get_last_error())
            size = c.c_size_t()
            k.InitializeProcThreadAttributeList(None, 1, 0, c.byref(size))
            attributes = c.create_string_buffer(size.value)
            self.check(k.InitializeProcThreadAttributeList(attributes, 1, 0, c.byref(size)))
            inherited = (w.HANDLE * 2)(writer.value, null)
            self.check(k.UpdateProcThreadAttribute(attributes, 0, 0x20002, c.byref(inherited), c.sizeof(inherited), None, None))
            startup = StartupEx()
            startup.startup.cb = c.sizeof(startup)
            startup.startup.flags = 0x100  # STARTF_USESTDHANDLES
            startup.startup.stdin = null
            startup.startup.stdout = startup.startup.stderr = writer
            startup.attributes = c.cast(attributes, w.LPVOID)
            environment = c.create_unicode_buffer('\0'.join(f'{key}={value}' for key, value in sorted(env.items(), key=lambda row: row[0].upper())) + '\0\0')
            command = c.create_unicode_buffer(subprocess.list2cmdline(self.args))
            # Suspended creation closes the assignment race: even an immediately
            # spawning child cannot escape ownership before ResumeThread.
            self.check(k.CreateProcessW(None, command, None, None, True, 0x4 | 0x400 | 0x80000,
                environment, str(cwd), c.byref(startup), c.byref(information)))
            self._process = information.process
            self.pid = information.pid
            self.check(k.AssignProcessToJobObject(self._job, self._process))
            if k.ResumeThread(information.thread) == 0xffffffff:
                raise c.WinError(c.get_last_error())
            descriptor = msvcrt.open_osfhandle(reader.value, os.O_RDONLY | os.O_BINARY)
            reader = w.HANDLE()
            self.stdout = os.fdopen(descriptor, 'rb')
            success = True
        finally:
            if attributes is not None:
                k.DeleteProcThreadAttributeList(attributes)
            for handle in (reader.value, writer.value, null, information.thread):
                if handle and handle != c.c_void_p(-1).value:
                    k.CloseHandle(handle)
            if not success:
                if self._process:
                    k.TerminateProcess(self._process, 1)
                self.close()

    @staticmethod
    def check(value):
        if not value:
            raise c.WinError(c.get_last_error())
        return value

    def poll(self):
        if self.returncode is not None:
            return self.returncode
        status = self.kernel.WaitForSingleObject(self._process, 0)
        if status == 258:
            return None
        self.check(status == 0)
        code = w.DWORD()
        self.check(self.kernel.GetExitCodeProcess(self._process, c.byref(code)))
        self.returncode = code.value
        return self.returncode

    def wait(self, timeout=None):
        status = self.kernel.WaitForSingleObject(self._process, 0xffffffff if timeout is None else min(0xfffffffe, int(timeout * 1000)))
        if status == 258:
            raise subprocess.TimeoutExpired(self.args, timeout)
        self.check(status == 0)
        return self.poll()

    def kill_tree(self):
        self.check(self.kernel.TerminateJobObject(self._job, 1))

    kill = kill_tree

    def close(self):
        for name in ('_job', '_process'):
            handle = getattr(self, name, None)
            if handle:
                self.kernel.CloseHandle(handle)
                setattr(self, name, None)
