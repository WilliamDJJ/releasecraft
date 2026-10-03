"""Disk-backed immutable archive snapshots and streamed member verification."""
from contextlib import contextmanager
import hashlib
import io
import json
from pathlib import Path
import struct
import tempfile
import zipfile

from .safety import ReleaseError, relative, open_safe
from .streaming import chunks, require_space

MANIFEST_BYTES = 16 * 1024 * 1024
DIRECTORY_BYTES = 64 * 1024 * 1024
MAX_EXPANSION_RATIO = 1000


class FrozenArchive:
    def __init__(self, stream, sha256, size):
        self.stream, self.sha256, self.size = stream, sha256, size


@contextmanager
def frozen_archive(value, operation=None):
    """One physical snapshot is shared by verification and extraction/runtime."""
    if isinstance(value, FrozenArchive):
        yield value
        return
    h = hashlib.sha256()
    if isinstance(value, bytes):
        with io.BytesIO(value) as stream:
            yield FrozenArchive(stream, hashlib.sha256(value).hexdigest(), len(value))
        return
    path = Path(value).absolute()
    with open_safe(path.parent, path.name) as (source, info):
        require_space(tempfile.gettempdir(), info.st_size)
        with tempfile.TemporaryFile('w+b') as target:
            for block in chunks(source, info.st_size, operation):
                target.write(block)
                h.update(block)
            target.flush()
            target.seek(0)
            yield FrozenArchive(target, h.hexdigest(), info.st_size)


def check_directory_size(frozen):
    """Bound ZIP metadata before Python materializes its central-directory list.

    Payload sizes have no aggregate cap. Central-directory metadata is separately
    bounded, including ZIP64; unsupported multi-disk files fail closed.
    """
    stream = frozen.stream
    stream.seek(max(0, frozen.size - 65557))
    tail = stream.read(65557)
    marker = tail.rfind(b'PK\x05\x06')
    if marker < 0 or len(tail) - marker < 22:
        raise ReleaseError('Missing ZIP directory')
    record = struct.unpack('<4s4H2LH', tail[marker:marker + 22])
    if record[1] or record[2] or record[3] != record[4] or len(tail) - marker != 22 + record[-1]:
        raise ReleaseError('Invalid ZIP directory')
    size, offset = record[5:7]
    absolute = frozen.size - len(tail) + marker
    if size == 0xffffffff or offset == 0xffffffff or record[4] == 0xffff:
        if absolute < 20:
            raise ReleaseError('Missing ZIP64 locator')
        stream.seek(absolute - 20)
        locator = struct.unpack('<4sLQL', stream.read(20))
        if locator[0] != b'PK\x06\x07' or locator[1] != 0 or locator[3] != 1:
            raise ReleaseError('Invalid ZIP64 locator')
        if locator[2] > absolute - 20 - 56:
            raise ReleaseError('ZIP64 directory offset outside archive')
        stream.seek(locator[2])
        raw = stream.read(56)
        if len(raw) != 56:
            raise ReleaseError('Incomplete ZIP64 directory')
        item = struct.unpack('<4sQ2H2L4Q', raw)
        if item[0] != b'PK\x06\x06' or item[4] or item[5] or item[6] != item[7]:
            raise ReleaseError('Invalid ZIP64 directory')
        size, offset = item[8:10]
    if size > DIRECTORY_BYTES or offset + size > absolute:
        raise ReleaseError('Archive directory metadata exceeds safe bound')
    stream.seek(0)


@contextmanager
def open_archive(frozen):
    check_directory_size(frozen)
    with zipfile.ZipFile(frozen.stream) as archive:
        yield archive


def member_index(archive):
    data, folded = {}, set()
    for info in archive.infolist():
        rel = relative(info.filename)
        key = rel.casefold()
        mode = info.external_attr >> 16
        if info.is_dir() or key in folded or mode & 0o170000 not in (0, 0o100000):
            raise ReleaseError('Duplicate, directory, link or special archive entry')
        if info.flag_bits & 1 or info.compress_type not in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED):
            raise ReleaseError('Encrypted or unsupported archive entry')
        if info.file_size > max(1, info.compress_size) * MAX_EXPANSION_RATIO:
            raise ReleaseError('Suspicious archive expansion ratio')
        folded.add(key)
        data[rel] = info
    for rel in data:
        parts = rel.casefold().split('/')
        if any('/'.join(parts[:i]) in folded for i in range(1, len(parts))):
            raise ReleaseError('File/directory prefix conflict')
    return data


def manifest_from(archive, members):
    info = members.get('RELEASE-MANIFEST.json')
    if info is None or info.file_size > MANIFEST_BYTES:
        raise ReleaseError('Missing or oversized manifest metadata')
    manifest = json.loads(archive.read(info))
    if not isinstance(manifest, dict) or manifest.get('schema') != 1 or not isinstance(manifest.get('files'), list):
        raise ReleaseError('Invalid manifest object')
    entries = manifest['files']
    expected = {row['path'] for row in entries}
    if len(expected) != len(entries) or expected != set(members) - {'RELEASE-MANIFEST.json'}:
        raise ReleaseError('Manifest file set mismatch')
    return manifest
