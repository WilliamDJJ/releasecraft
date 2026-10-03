"""Windows handle-based file reads and bounded process-tree lifecycle."""

from __future__ import annotations
import ctypes
from contextlib import contextmanager
from ctypes import wintypes as w
import os
from pathlib import Path


def kernel():
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    k.CloseHandle.argtypes = [w.HANDLE]
    k.CloseHandle.restype = w.BOOL
    return k


def checked(ok):
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


class FileInfo(ctypes.Structure):
    _fields_ = [
        ("attributes", w.DWORD),
        ("creation", w.FILETIME),
        ("access", w.FILETIME),
        ("write", w.FILETIME),
        ("volume", w.DWORD),
        ("size_high", w.DWORD),
        ("size_low", w.DWORD),
        ("links", w.DWORD),
        ("index_high", w.DWORD),
        ("index_low", w.DWORD),
    ]


@contextmanager
def open_locked(root, rel, limit=None):
    """Hold every ancestor without delete sharing until the selected file is read."""
    if (
        not isinstance(rel, str)
        or not rel
        or "\\" in rel
        or any(part in ("", ".", "..") or ":" in part for part in rel.split("/"))
    ):
        raise OSError("Invalid relative path")
    import msvcrt

    k = kernel()
    k.CreateFileW.argtypes = [
        w.LPCWSTR,
        w.DWORD,
        w.DWORD,
        w.LPVOID,
        w.DWORD,
        w.DWORD,
        w.HANDLE,
    ]
    k.CreateFileW.restype = w.HANDLE
    k.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(FileInfo)]
    k.GetFileInformationByHandle.restype = w.BOOL
    full = Path(root).absolute().joinpath(*rel.split("/"))
    if str(full).startswith("\\\\"):
        raise OSError("UNC sources are not supported")
    handles = []
    current = Path(full.anchor)
    try:
        components = [current]
        for part in full.parts[1:]:
            current = current / part
            components.append(current)
        for i, path in enumerate(components):
            is_file = i == len(components) - 1
            handle = k.CreateFileW(
                str(path),
                0x80000000 if is_file else 0x80,
                1,
                None,
                3,
                0x00200000 | 0x02000000,
                None,
            )
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            handles.append(handle)
            info = FileInfo()
            checked(k.GetFileInformationByHandle(handle, ctypes.byref(info)))
            if info.attributes & 0x400:
                raise OSError("Reparse point rejected")
            if not is_file and not info.attributes & 0x10:
                raise OSError("Expected directory")
            if is_file:
                size = (info.size_high << 32) | info.size_low
                if info.attributes & 0x10 or info.links != 1 or (limit is not None and size > limit):
                    raise OSError("Unsafe file")
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
                handles.pop()
                with os.fdopen(fd, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    yield stream, before
                    after = os.fstat(stream.fileno())
                if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                    after.st_size, after.st_mtime_ns, after.st_ctime_ns,
                ):
                    raise OSError("File changed")
                return
    finally:
        for handle in reversed(handles):
            k.CloseHandle(handle)
    raise OSError("Missing file")


def read_locked(root, rel, limit):
    with open_locked(root, rel, limit) as (stream, before):
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise OSError("File changed")
    return data, bool(before.st_mode & 0o111)


class BasicLimit(ctypes.Structure):
    _fields_ = [
        ("process_time", ctypes.c_int64),
        ("job_time", ctypes.c_int64),
        ("flags", w.DWORD),
        ("minimum", ctypes.c_size_t),
        ("maximum", ctypes.c_size_t),
        ("active", w.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class IO(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class ExtendedLimit(ctypes.Structure):
    _fields_ = [
        ("basic", BasicLimit),
        ("io", IO),
        ("process_memory", ctypes.c_size_t),
        ("job_memory", ctypes.c_size_t),
        ("peak_process", ctypes.c_size_t),
        ("peak_job", ctypes.c_size_t),
    ]


class ThreadEntry(ctypes.Structure):
    _fields_ = [
        ("size", w.DWORD),
        ("usage", w.DWORD),
        ("tid", w.DWORD),
        ("pid", w.DWORD),
        ("priority", w.LONG),
        ("delta", w.LONG),
        ("flags", w.DWORD),
    ]


class ProcessJob:
    """Assign a suspended subprocess before allowing it to spawn descendants."""

    def __init__(self, process):
        self.k = kernel()
        k = self.k
        self.handle = None
        k.CreateJobObjectW.argtypes = [w.LPVOID, w.LPCWSTR]
        k.CreateJobObjectW.restype = w.HANDLE
        k.SetInformationJobObject.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
        k.SetInformationJobObject.restype = w.BOOL
        k.AssignProcessToJobObject.argtypes = [w.HANDLE, w.HANDLE]
        k.AssignProcessToJobObject.restype = w.BOOL
        k.TerminateJobObject.argtypes = [w.HANDLE, w.UINT]
        k.TerminateJobObject.restype = w.BOOL
        try:
            self.handle = k.CreateJobObjectW(None, None)
            checked(self.handle)
            limits = ExtendedLimit()
            limits.basic.flags = 0x2000
            checked(
                k.SetInformationJobObject(
                    self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)
                )
            )
            checked(k.AssignProcessToJobObject(self.handle, int(process._handle)))
            self._resume(process.pid)
        except BaseException:
            self.close()
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)
            raise

    def _resume(self, pid):
        k = self.k
        k.CreateToolhelp32Snapshot.argtypes = [w.DWORD, w.DWORD]
        k.CreateToolhelp32Snapshot.restype = w.HANDLE
        k.Thread32First.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        k.Thread32First.restype = w.BOOL
        k.Thread32Next.argtypes = [w.HANDLE, ctypes.POINTER(ThreadEntry)]
        k.Thread32Next.restype = w.BOOL
        k.OpenThread.argtypes = [w.DWORD, w.BOOL, w.DWORD]
        k.OpenThread.restype = w.HANDLE
        k.ResumeThread.argtypes = [w.HANDLE]
        k.ResumeThread.restype = w.DWORD
        snapshot = k.CreateToolhelp32Snapshot(4, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = ThreadEntry()
            entry.size = ctypes.sizeof(entry)
            ok = k.Thread32First(snapshot, ctypes.byref(entry))
            while ok:
                if entry.pid == pid:
                    thread = k.OpenThread(2, False, entry.tid)
                    checked(thread)
                    try:
                        if k.ResumeThread(thread) == 0xFFFFFFFF:
                            raise ctypes.WinError(ctypes.get_last_error())
                    finally:
                        k.CloseHandle(thread)
                    return
                ok = k.Thread32Next(snapshot, ctypes.byref(entry))
            raise OSError("Suspended process thread not found")
        finally:
            k.CloseHandle(snapshot)

    def terminate(self):
        if self.handle:
            checked(self.k.TerminateJobObject(self.handle, 1))

    def close(self):
        if self.handle:
            self.k.CloseHandle(self.handle)
            self.handle = None
