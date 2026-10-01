"""Anchored directory operations for owned output; no reparse traversal or overwrite."""
from __future__ import annotations
import ctypes
from itertools import islice
import os
from pathlib import Path
import stat
from .safety import ReleaseError, digest, linked, relative


def identity(info):
    return [info.st_dev, info.st_ino]


class Directory:
    """Pin directory ancestors on Windows; use no-follow directory FDs on Linux.

    POSIX writes remain anchored to the selected inode, even during a rename;
    name/identity checks fail the operation when the selected location changes.
    """
    def __init__(self, path, create=False):
        self.path = Path(os.path.abspath(path))
        self.handles = []
        self.fd = None
        self.stamp = None
        if str(self.path).startswith("\\\\"):
            raise ReleaseError("Network output is not supported")
        if os.name not in ("nt", "posix"):
            raise ReleaseError("Unsupported directory backend")
        try:
            current = Path(self.path.anchor)
            parts = list(self.path.parts[1:])
            if os.name == "nt":
                self._pin_windows(current)
                for part in parts:
                    current /= part
                    if create and not current.exists():
                        current.mkdir(mode=0o700)
                    self._pin_windows(current)
            else:
                self.fd = os.open(current, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                for part in parts:
                    if create:
                        try:
                            os.mkdir(part, 0o700, dir_fd=self.fd)
                        except FileExistsError:
                            pass
                    nxt = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=self.fd)
                    os.close(self.fd)
                    self.fd = nxt
            info = self.path.lstat()
            if linked(self.path) or not stat.S_ISDIR(info.st_mode):
                raise ReleaseError("Unsafe directory")
            self.stamp = identity(info)
            self.check()
        except BaseException:
            self.close()
            raise

    def _pin_windows(self, path):
        from ctypes import wintypes as w
        from .windows import kernel, FileInfo, checked
        self.kernel = kernel()
        k = self.kernel
        k.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE]
        k.CreateFileW.restype = w.HANDLE
        k.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(FileInfo)]
        k.GetFileInformationByHandle.restype = w.BOOL
        handle = k.CreateFileW(str(path), 0x80, 3, None, 3, 0x00200000 | 0x02000000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        self.handles.append(handle)
        info = FileInfo()
        checked(k.GetFileInformationByHandle(handle, ctypes.byref(info)))
        if info.attributes & 0x400 or not info.attributes & 0x10:
            raise ReleaseError("Directory reparse points are not supported")

    def check(self):
        if self.stamp is None:
            raise ReleaseError("Closed directory")
        if linked(self.path) or identity(self.path.lstat()) != self.stamp:
            raise ReleaseError("Directory location changed")
        if self.fd is not None and identity(os.fstat(self.fd)) != self.stamp:
            raise ReleaseError("Directory handle changed")

    @staticmethod
    def name(name):
        relative(name)
        if "/" in name:
            raise ReleaseError("Expected one path component")
        return name

    def mkdir(self, name):
        self.check()
        name = self.name(name)
        if self.fd is None:
            (self.path / name).mkdir(mode=0o700)
        else:
            os.mkdir(name, 0o700, dir_fd=self.fd)
        self.check()

    def write_new(self, name, data):
        self.check()
        name = self.name(name)
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(self.path / name, flags, 0o600) if self.fd is None else os.open(name, flags, 0o600, dir_fd=self.fd)
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
            written = identity(os.fstat(stream.fileno()))
        self.check()
        return written

    def commit_directory(self, temporary, final):
        self.check()
        self.name(temporary)
        self.name(final)
        if self.fd is None:
            os.rename(self.path / temporary, self.path / final)
        else:
            libc = ctypes.CDLL(None, use_errno=True)
            rename = getattr(libc, 'renameat2', None)
            if rename is None:
                raise ReleaseError('Atomic directory publication requires Linux renameat2')
            rename.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
            rename.restype = ctypes.c_int
            if rename(self.fd, os.fsencode(temporary), self.fd, os.fsencode(final), 1):
                raise OSError(ctypes.get_errno(), 'Atomic output publication failed')
        self.check()

    def commit_verified(self, temporary, final, expected_directory, expected_files):
        """Seal known payloads and publish without following a substituted path.

        Windows locks files for verification and renames the pinned directory
        handle; Windows requires child handles closed during directory rename.
        Linux anchors reads/rename to directory FDs. Both verify names and bytes
        again at the published location before reporting success. This is not a sandbox
        against another process running with the same user's authority.
        """
        self.check()
        self.name(temporary)
        self.name(final)
        path = self.path / temporary
        streams = []
        handle = None
        directory = None
        try:
            if os.name == 'nt':
                from ctypes import wintypes as w
                from .windows import FileInfo, checked
                import msvcrt
                k = self.kernel
                handle = k.CreateFileW(str(path), 0x10080, 3, None, 3, 0x02200000, None)
                if handle == ctypes.c_void_p(-1).value:
                    handle = None
                    raise ctypes.WinError(ctypes.get_last_error())
                info = FileInfo()
                checked(k.GetFileInformationByHandle(handle, ctypes.byref(info)))
                if info.attributes & 0x400 or not info.attributes & 0x10:
                    raise ReleaseError('Unsafe publication directory')
            else:
                directory = Directory(path)
            if identity(path.lstat()) != expected_directory:
                raise ReleaseError('Publication directory was replaced')
            if {p.name for p in islice(path.iterdir(), len(expected_files) + 1)} != set(expected_files):
                raise ReleaseError('Publication file set changed')
            for name, (stamp, sha, size) in expected_files.items():
                self.name(name)
                if os.name == 'nt':
                    file_handle = k.CreateFileW(str(path / name), 0x80000000, 1, None, 3, 0x00200000, None)
                    if file_handle == ctypes.c_void_p(-1).value:
                        raise ctypes.WinError(ctypes.get_last_error())
                    try:
                        fd = msvcrt.open_osfhandle(file_handle, os.O_RDONLY | os.O_BINARY)
                    except BaseException:
                        k.CloseHandle(file_handle)
                        raise
                else:
                    fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory.fd)
                stream = os.fdopen(fd, 'rb')
                streams.append(stream)
                info = os.fstat(fd)
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or identity(info) != stamp or info.st_size != size:
                    raise ReleaseError('Publication file was replaced')
                if digest(stream.read(size + 1)) != sha:
                    raise ReleaseError('Publication content changed')
            if os.name == 'nt':
                for stream in streams:
                    stream.close()
                streams.clear()
                target = str(self.path / final)
                class RenameInfo(ctypes.Structure):
                    _fields_ = [('flags', w.DWORD), ('root', w.HANDLE), ('length', w.DWORD), ('name', w.WCHAR * (len(target.encode('utf-16-le')) // 2 + 1))]
                rename = RenameInfo()
                rename.length = len(target.encode('utf-16-le'))
                rename.name = target
                k.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
                k.SetFileInformationByHandle.restype = w.BOOL
                checked(k.SetFileInformationByHandle(handle, 3, ctypes.byref(rename), ctypes.sizeof(rename)))
                k.CloseHandle(handle)
                handle = None
                directory = Directory(self.path / final)
            else:
                directory.check()
                self.commit_directory(temporary, final)
            if identity((self.path / final).lstat()) != expected_directory:
                raise ReleaseError('Publication location changed')
            from .safety import read_safe
            final_path = self.path / final
            if {p.name for p in islice(final_path.iterdir(), len(expected_files) + 1)} != set(expected_files):
                raise ReleaseError('Published file set changed')
            for name, (stamp, sha, size) in expected_files.items():
                if identity((final_path / name).lstat()) != stamp or digest(read_safe(final_path, name, size)[0]) != sha:
                    raise ReleaseError('Published content changed')
            for stream, (stamp, sha, size) in zip(streams, expected_files.values()):
                stream.seek(0)
                if digest(stream.read(size + 1)) != sha or identity(os.fstat(stream.fileno())) != stamp:
                    raise ReleaseError('Publication changed during commit')
            self.check()
        finally:
            for stream in streams:
                stream.close()
            if handle is not None:
                self.kernel.CloseHandle(handle)
            if directory is not None:
                directory.close()
    def remove_verified(self, name, record):
        """Delete a recorded entry only; Windows deletes the verified handle."""
        self.check()
        self.name(name)
        path = self.path / name
        directory = record['kind'] == 'directory'
        if os.name == 'nt':
            import msvcrt
            from ctypes import wintypes as w
            from .windows import checked
            k = self.kernel
            handle = k.CreateFileW(str(path), 0x80010000, 1, None, 3, 0x02200000, None)
            if handle == ctypes.c_void_p(-1).value:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
            except BaseException:
                k.CloseHandle(handle)
                raise
        else:
            fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | (os.O_DIRECTORY if directory else 0), dir_fd=self.fd)
        try:
            info = os.fstat(fd)
            if identity(info) != record['identity'] or linked(path):
                raise ReleaseError('Cleanup entry replaced; retained')
            if directory:
                if not stat.S_ISDIR(info.st_mode):
                    raise ReleaseError('Cleanup directory replaced')
            else:
                if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size != record['size']:
                    raise ReleaseError('Cleanup file replaced')
                import hashlib
                hasher = hashlib.sha256()
                remaining = record['size'] + 1
                while remaining:
                    chunk = os.read(fd, min(65536, remaining))
                    if not chunk:
                        break
                    hasher.update(chunk)
                    remaining -= len(chunk)
                if hasher.hexdigest() != record['sha256']:
                    raise ReleaseError('Cleanup file changed')
            if os.name == 'nt':
                k.SetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.c_int, w.LPVOID, w.DWORD]
                k.SetFileInformationByHandle.restype = w.BOOL
                delete = w.BOOL(True)
                checked(k.SetFileInformationByHandle(msvcrt.get_osfhandle(fd), 4, ctypes.byref(delete), ctypes.sizeof(delete)))
            else:
                if identity(path.lstat()) != record['identity']:
                    raise ReleaseError('Cleanup entry moved')
                if directory:
                    os.rmdir(name, dir_fd=self.fd)
                else:
                    os.unlink(name, dir_fd=self.fd)
        finally:
            os.close(fd)

    def remove_file(self, name, expected=None):
        self.check()
        self.name(name)
        if expected is not None and identity((self.path / name).lstat()) != expected:
            raise ReleaseError("Created file was replaced; retained for review")
        if self.fd is None:
            (self.path / name).unlink()
        else:
            os.unlink(name, dir_fd=self.fd)

    def remove_directory(self, name):
        self.check()
        self.name(name)
        if self.fd is None:
            (self.path / name).rmdir()
        else:
            os.rmdir(name, dir_fd=self.fd)

    def close(self):
        for handle in reversed(self.handles):
            self.kernel.CloseHandle(handle)
        self.handles = []
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
        self.stamp = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
