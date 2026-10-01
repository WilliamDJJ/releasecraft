"""Bounded private work, creation journals, and explicit audit retention.

One OS lease serializes admission, work and maintenance. Unknown content is
counted, never adopted. Journals are private evidence, not a sandbox against
another process with the same user's authority.
"""
from __future__ import annotations
from contextlib import contextmanager
import io
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import time
import uuid
import zipfile

from .directory import Directory, identity
from .safety import ReleaseError, atomic_json, canonical, digest, linked, read_safe, relative

STATE_BYTES = 1024 * 1024 * 1024
STAGE_BYTES = 640 * 1024 * 1024
AUDIT_BYTES = 16 * 1024 * 1024
TOTAL_AUDITS = 64 * 1024 * 1024
AUDIT_COUNT = 20
HISTORY_COUNT = 100
OWNER_COUNT = 256
ENTRY_COUNT = 50000
JOURNAL_BYTES = 12 * 1024 * 1024
INDEX_BYTES = 2 * 1024 * 1024


class StorageBlocked(ReleaseError):
    """Private capacity or ownership cannot be safely established."""


def measure(root):
    """Metadata-only bound including unknown files; never follow a link."""
    total = entries = 0
    stack = [(Path(root), 0)]
    while stack:
        path, depth = stack.pop()
        if depth > 72:
            raise StorageBlocked('Private storage depth limit')
        with Directory(path), os.scandir(path) as listing:
            for entry in listing:
                entries += 1
                if entries > ENTRY_COUNT:
                    raise StorageBlocked('Private storage entry limit')
                # Windows DirEntry caches do not populate link counts/inodes.
                info = os.stat(entry.path, follow_symlinks=False)
                if stat.S_ISLNK(info.st_mode) or getattr(info, 'st_file_attributes', 0) & 0x400:
                    raise StorageBlocked('Private storage contains an unverified link')
                if stat.S_ISDIR(info.st_mode):
                    stack.append((Path(entry.path), depth + 1))
                elif stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                    total += info.st_size
                else:
                    raise StorageBlocked('Private storage contains an unsafe entry')
    return {'bytes': total, 'entries': entries}


class OwnedTree:
    """Only entries recorded at creation can be cleaned, with exact identity/bytes."""
    def __init__(self, path, journal, stamp, journal_stamp, create=False):
        self.path, self.journal = Path(path), Path(journal)
        self.stamp, self.journal_stamp = stamp, journal_stamp
        self.records = {}
        self.written = 0
        self.limit = AUDIT_BYTES
        if not create:
            data = read_safe(self.journal.parent, self.journal.name, JOURNAL_BYTES)[0]
            if identity(self.journal.lstat()) != journal_stamp:
                raise StorageBlocked('Private journal was replaced')
            for line in data.splitlines():
                row = json.loads(line)
                name = relative(row['path'])
                if row['kind'] == 'removed':
                    self.records.pop(name, None)
                elif row['kind'] in ('file', 'directory'):
                    if row['kind'] == 'file' and (type(row.get('size')) is not int or not 0 <= row['size'] <= STAGE_BYTES + AUDIT_BYTES):
                        raise StorageBlocked('Invalid private journal size')
                    self.records[name] = row
                else:
                    raise StorageBlocked('Invalid private journal')
                if len(self.records) > ENTRY_COUNT:
                    raise StorageBlocked('Private journal entry limit')

    def append(self, row):
        blob = json.dumps(row, sort_keys=True, ensure_ascii=False).encode() + b'\n'
        with Directory(self.journal.parent) as parent:
            if identity(self.journal.lstat()) != self.journal_stamp or linked(self.journal):
                raise StorageBlocked('Private journal changed')
            flags = os.O_WRONLY | os.O_APPEND | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(self.journal, flags) if parent.fd is None else os.open(self.journal.name, flags, dir_fd=parent.fd)
            with os.fdopen(fd, 'ab') as stream:
                info = os.fstat(stream.fileno())
                if identity(info) != self.journal_stamp or info.st_nlink != 1 or info.st_size + len(blob) > JOURNAL_BYTES:
                    raise StorageBlocked('Private journal limit or replacement')
                stream.write(blob)
                stream.flush()
                os.fsync(stream.fileno())
        if row['kind'] == 'removed':
            self.records.pop(row['path'], None)
        else:
            self.records[row['path']] = row

    def check(self):
        with Directory(self.path) as root:
            if root.stamp != self.stamp:
                raise StorageBlocked('Private job directory replaced')

    def mkdir(self, rel):
        self.check()
        relative(rel)
        parts = PurePosixPath(rel).parts
        for i in range(1, len(parts) + 1):
            name = '/'.join(parts[:i])
            path = self.path / name
            if name in self.records:
                with Directory(path) as present:
                    if self.records[name]['kind'] != 'directory' or present.stamp != self.records[name]['identity']:
                        raise StorageBlocked('Private directory replaced')
                continue
            with Directory(path.parent) as parent:
                parent.mkdir(path.name)
                with Directory(path) as created:
                    self.append({'path': name, 'kind': 'directory', 'identity': created.stamp})

    @contextmanager
    def open_new(self, rel):
        self.check()
        relative(rel)
        if '/' in rel:
            self.mkdir(rel.rsplit('/', 1)[0])
        path = self.path / rel
        with Directory(path.parent) as parent:
            flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0) | getattr(os, 'O_NOFOLLOW', 0)
            fd = os.open(path, flags, 0o600) if parent.fd is None else os.open(path.name, flags, 0o600, dir_fd=parent.fd)
            tree = self
            class BoundedFile(io.BufferedRandom):
                def write(self, data):
                    if tree.written + len(data) > tree.limit:
                        raise StorageBlocked('Private write reservation exhausted')
                    tree.written += len(data)
                    return super().write(data)
            with BoundedFile(io.FileIO(fd, 'r+', closefd=True)) as stream:
                try:
                    yield stream
                finally:
                    stream.flush()
                    os.fsync(stream.fileno())
                    info = os.fstat(stream.fileno())
                    stream.seek(0)
                    import hashlib
                    hasher = hashlib.sha256()
                    while chunk := stream.read(65536):
                        hasher.update(chunk)
                    # Interrupted writes without a final journal record are unknown
                    # and retained on recovery, rather than guessed to be owned.
                    self.append({'path': rel, 'kind': 'file', 'identity': identity(info), 'size': info.st_size, 'sha256': hasher.hexdigest()})

    def write(self, rel, data):
        with self.open_new(rel) as stream:
            stream.write(data)

    def selected(self, prefix=None):
        return {p:r for p,r in self.records.items() if prefix is None or p == prefix or p.startswith(prefix + '/')}

    def verify(self, prefix=None):
        self.check()
        rows = self.selected(prefix)
        start = self.path / prefix if prefix else self.path
        if prefix and prefix not in rows:
            if start.exists():
                raise StorageBlocked('Unregistered private staging')
            return rows
        observed = set()
        stack = [start]
        if prefix:
            observed.add(prefix)
            with Directory(start) as selected:
                if selected.stamp != rows[prefix]['identity']:
                    raise StorageBlocked('Staging root replaced')
        while stack:
            folder = stack.pop()
            with Directory(folder), os.scandir(folder) as listing:
                for entry in listing:
                    name = (folder / entry.name).relative_to(self.path).as_posix()
                    if name not in rows:
                        raise StorageBlocked('Unknown private content retained')
                    observed.add(name)
                    row = rows[name]
                    info = os.stat(entry.path, follow_symlinks=False)
                    if identity(info) != row['identity'] or linked(Path(entry.path)):
                        raise StorageBlocked('Private entry changed')
                    if row['kind'] == 'directory' and stat.S_ISDIR(info.st_mode):
                        stack.append(Path(entry.path))
                    elif row['kind'] == 'file' and stat.S_ISREG(info.st_mode) and info.st_nlink == 1:
                        if info.st_size != row['size'] or digest(read_safe(folder, entry.name, row['size'])[0]) != row['sha256']:
                            raise StorageBlocked('Private content changed')
                    else:
                        raise StorageBlocked('Unsafe private entry')
        if observed != set(rows):
            raise StorageBlocked('Private entry missing')
        return rows

    def clean(self, prefix=None):
        rows = self.verify(prefix)
        freed = 0
        for name, row in sorted(rows.items(), key=lambda item: (item[0].count('/'), item[0]), reverse=True):
            path = self.path / name
            with Directory(path.parent) as parent:
                parent.remove_verified(path.name, row)
            self.append({'path': name, 'kind': 'removed'})
            freed += row.get('size', 0)
        return freed


class Storage:
    def __init__(self, root):
        self.root = Path(root)
        self.index = []
        self.active = None
        self.index_identity = None
        self.index_sha256 = None

    def __enter__(self):
        from .managed import lease
        self.directory = Directory(self.root, create=True)
        try:
            try:
                self.directory.write_new('.lease', b'0')
            except FileExistsError:
                pass
            self.lock = lease(self.directory)
            self.lock.__enter__()
            for name in ('jobs', 'journals', 'owners'):
                with Directory(self.root / name, create=True):
                    pass
            if os.path.lexists(self.root / 'storage-index.json'):
                blob = read_safe(self.root, 'storage-index.json', INDEX_BYTES)[0]
                value = json.loads(blob)
                self.index_identity = identity((self.root / 'storage-index.json').lstat())
                self.index_sha256 = digest(blob)
                if value['schema'] != 1 or not isinstance(value['jobs'], list) or len(value['jobs']) > HISTORY_COUNT:
                    raise StorageBlocked('Invalid storage history')
                self.index = value['jobs']
                for row in self.index:
                    if not isinstance(row['id'], str) or len(row['id']) != 32 or any(c not in '0123456789abcdef' for c in row['id']):
                        raise StorageBlocked('Invalid job identifier')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if getattr(self, 'lock', None):
            self.lock.__exit__(*args)
            self.lock = None
        self.directory.close()

    def check_index(self):
        self.directory.check()
        path = self.root / 'storage-index.json'
        if self.index_identity is None:
            if os.path.lexists(path):
                raise StorageBlocked('Unregistered private index retained')
        elif (identity(path.lstat()) != self.index_identity
              or digest(read_safe(self.root, path.name, INDEX_BYTES)[0]) != self.index_sha256):
            raise StorageBlocked('Private index changed; retained')

    def save(self):
        value = {'schema': 1, 'jobs': self.index}
        if len(canonical(value)) > INDEX_BYTES:
            raise StorageBlocked('Storage history size limit')
        self.check_index()
        blob = canonical(value)
        if self.index_identity is None:
            self.directory.write_new('storage-index.json', blob)
        else:
            atomic_json(self.root / 'storage-index.json', value)
        self.index_identity = identity((self.root / 'storage-index.json').lstat())
        self.index_sha256 = digest(blob)

    def tree(self, row):
        return OwnedTree(self.root / 'jobs' / row['id'], self.root / 'journals' / (row['id'] + '.jsonl'), row['identity'], row['journal_identity'])

    def capacity(self, reservation=0):
        used = measure(self.root)
        if used['bytes'] + reservation > STATE_BYTES or shutil.disk_usage(self.root).free < reservation:
            raise StorageBlocked('Private storage capacity exceeded')
        return used

    def new_job(self):
        self.maintain()
        self.capacity(AUDIT_BYTES + JOURNAL_BYTES + INDEX_BYTES)
        if len([r for r in self.index if r.get('retained')]) >= HISTORY_COUNT:
            raise StorageBlocked('Retained private jobs need review')
        identifier = uuid.uuid4().hex
        with Directory(self.root / 'jobs') as jobs, Directory(self.root / 'journals') as journals:
            jobs.mkdir(identifier)
            with Directory(self.root / 'jobs' / identifier) as job:
                stamp = job.stamp
            journal_stamp = journals.write_new(identifier + '.jsonl', b'')
        row = {'id': identifier, 'identity': stamp, 'journal_identity': journal_stamp, 'status':'RUNNING', 'created':time.time(), 'retained':True}
        self.index.append(row)
        # Evicted compact records have no retained directory. Never forget an
        # ambiguous job merely to make room in the history.
        while len(self.index) > HISTORY_COUNT:
            empty = next((r for r in self.index if not r.get('retained')), None)
            if empty is None:
                raise StorageBlocked('Private history is full')
            self.index.remove(empty)
        self.save()
        self.active = row
        return row, OwnedTree(self.root / 'jobs' / identifier, self.root / 'journals' / (identifier + '.jsonl'), stamp, journal_stamp, create=True)

    def reserve_stage(self, plan, tree):
        # UTF-8 names, manifests, ZIP headers and transformed notebook expansion
        # are bounded separately. Actual writes must fit this reservation too.
        selected = [r for r in plan['files'] if r['state'] in ('INCLUDE', 'TRANSFORM')]
        total = sum(r['size'] * (6 if r['state'] == 'TRANSFORM' else 1) for r in selected)
        total += sum(len(t.encode()) for t in plan.get('generated_files', {}).values())
        overhead = len(canonical(plan)) * 3 + sum(len(r['path'].encode()) * 12 + 2048 for r in selected) + 65536
        reserve = total * 2 + overhead
        if reserve > STAGE_BYTES:
            raise StorageBlocked('Private staging reservation limit')
        self.capacity(reserve + AUDIT_BYTES + JOURNAL_BYTES)
        tree.limit = tree.written + reserve + AUDIT_BYTES
        self.active['reservation_bytes'] = reserve
        self.save()

    def finish(self, tree, result):
        row = self.active
        if row is None:
            return
        try:
            tree.clean('stage')
            cleanup = 'CLEAN'
        except (OSError, ReleaseError, ValueError, KeyError, TypeError):
            cleanup = 'RETAINED'
            result['storage_warning'] = 'private-staging-retained'
        encoded = canonical(result)
        try:
            if len(encoded) + sum(r.get('size', 0) for p,r in tree.records.items() if not p.startswith('stage')) > AUDIT_BYTES:
                raise StorageBlocked('Private audit size limit')
            tree.limit += len(encoded)
            tree.write('status.json', encoded)
        except (OSError, ReleaseError):
            result['storage_warning'] = 'private-audit-incomplete'
        row.update(status=result['status'], cleanup=cleanup, completed=time.time(), reservation_bytes=0,
                   audit_bytes=sum(r.get('size', 0) for p,r in tree.records.items() if not p.startswith('stage')))
        for key in ('archive_sha256', 'payload_files', 'archive_bytes'):
            if key in result:
                row[key] = result[key]
        self.active = None
        self.save()
        self.maintain()

    def maintain(self, clear=False):
        self.check_index()
        count = total = 0
        for row in reversed(self.index):
            if row is self.active or not row.get('retained'):
                continue
            try:
                tree = self.tree(row)
                # Holding the global OS lease proves a RUNNING record is from
                # an interrupted process, not a currently active operation.
                tree.clean('stage')
                if row['status'] == 'RUNNING':
                    row.update(status='INTERRUPTED', reservation_bytes=0)
                rows = tree.verify()
                size = sum(r.get('size', 0) for r in rows.values())
                if not clear and count < AUDIT_COUNT and total + size <= TOTAL_AUDITS:
                    count += 1
                    total += size
                    row['audit_bytes'] = size
                    row['cleanup'] = 'CLEAN'
                    continue
                tree.clean()
                with Directory(self.root / 'jobs') as jobs:
                    jobs.remove_verified(row['id'], {'kind':'directory','identity':row['identity']})
                blob = read_safe(self.root / 'journals', row['id'] + '.jsonl', JOURNAL_BYTES)[0]
                with Directory(self.root / 'journals') as journals:
                    journals.remove_verified(row['id'] + '.jsonl', {'kind':'file','identity':row['journal_identity'], 'size':len(blob),'sha256':digest(blob)})
                row.update(retained=False, audit_bytes=0, cleanup='CLEAN')
            except (OSError, ReleaseError, ValueError, KeyError, TypeError):
                row['cleanup'] = 'RETAINED'
        self.save()

    def snapshot(self):
        used = measure(self.root)
        return {**used, 'limit_bytes': STATE_BYTES, 'jobs': list(reversed(self.index)), 'unverified_possible':True}


def storage_status(state):
    try:
        with Storage(state) as store:
            return {'status':'AVAILABLE', **store.snapshot()}
    except (OSError, ReleaseError, ValueError, KeyError, TypeError):
        return {'status':'UNAVAILABLE', 'jobs':[]}


def clean_storage(state, clear_audits=False):
    with Storage(state) as store:
        before = measure(store.root)['bytes']
        store.maintain(clear=clear_audits)
        after = measure(store.root)['bytes']
        return {'status':'COMPLETE', 'freed_bytes':max(0, before - after), **store.snapshot()}


def export_audit(state, identifier, destination):
    """Exact retained audit bytes only, explicit destination, never overwrite."""
    with Storage(state) as store:
        row = next(r for r in store.index if r['id'] == identifier and r.get('retained'))
        tree = store.tree(row)
        tree.check()
        rows = {n:r for n,r in tree.records.items() if r['kind']=='file' and not n.startswith('stage/')}
        if sum(r['size'] for r in rows.values()) > AUDIT_BYTES:
            raise StorageBlocked('Private export size limit')
        payload = {}
        for name, record in rows.items():
            blob = read_safe(tree.path, name, AUDIT_BYTES)[0]
            if identity((tree.path/name).lstat()) != record['identity'] or len(blob) != record['size'] or digest(blob) != record['sha256']:
                raise StorageBlocked('Private audit changed')
            payload[name] = blob
        destination = Path(destination)
        from .safety import separate
        separate(state, destination)
        with Directory(destination.parent), destination.open('xb') as stream, zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_STORED) as archive:
            for name, blob in sorted(payload.items()):
                archive.writestr(name, blob)
