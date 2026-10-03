"""Chunked content checks and hashes; payload size is not a project admission limit."""
from __future__ import annotations

from dataclasses import dataclass
import codecs
import hashlib
import json
from pathlib import Path
import re
import shutil

from .operation import signal
from .safety import ReleaseError, findings, open_safe, read_safe

CHUNK_BYTES = 1024 * 1024
PARSE_BYTES = 16 * 1024 * 1024
CACHE_BYTES = 32 * 1024 * 1024
SCAN_WINDOW = 65536
SCAN_OVERLAP = 4096


class SpaceError(ReleaseError):
    """An operation cannot fit its estimated bytes on the destination device."""


def require_space(path, required):
    path = Path(path)
    while not path.exists():
        path = path.parent
    if shutil.disk_usage(path).free < required:
        raise SpaceError("Insufficient destination space")


def chunks(stream, size=None, operation=None, phase="Reading", current=None):
    """A known size detects growth; every iteration observes cancellation."""
    total = 0
    while True:
        signal(operation, phase, current=current, bytes_read=total, total_files=None)
        amount = CHUNK_BYTES if size is None else min(CHUNK_BYTES, size + 1 - total)
        if amount <= 0:
            raise ReleaseError("Content grew during read")
        data = stream.read(amount)
        if not data:
            break
        total += len(data)
        if size is not None and total > size:
            raise ReleaseError("Content grew during read")
        yield data
    if size is not None and total != size:
        raise ReleaseError("Content size changed during read")


def hash_stream(stream, size=None, operation=None):
    h = hashlib.sha256()
    for data in chunks(stream, size, operation):
        h.update(data)
    return h.hexdigest()


def hash_file(path, operation=None):
    path = Path(path).absolute()
    with open_safe(path.parent, path.name) as (stream, info):
        return hash_stream(stream, info.st_size, operation)


def copy_safe(root, rel, target, *, expected=None, operation=None):
    h = hashlib.sha256()
    with open_safe(root, rel) as (stream, info):
        for block in chunks(stream, info.st_size, operation, "Copying bytes", rel):
            target.write(block)
            h.update(block)
    if expected is not None and h.hexdigest() != expected:
        raise ReleaseError("Source changed while copying")
    return h.hexdigest(), info.st_size, bool(info.st_mode & 0o111)


class ContentScanner:
    """Small structured files keep existing exact checks; large payloads use windows.

    Overlapping windows cover split recognizers. An overlong unfinished text line
    containing a sensitive recognizer prefix, or an unfinished credential
    assignment across lines, is conservatively blocked instead of silently
    dropping unbounded match context. Large code/structured files
    still need the separate parser gate; opaque resources have no size cap.
    """
    suspicious = re.compile(rb'(?i)(password|passwd|api[_-]?key|access[_-]?token|secret[_-]?key|_auth|://|PRIVATE KEY|gh[pousr]_|github_pat_|sk-|xox[baprs]-|/' + rb'Users/|/' + rb'home/|\\Users\\)')
    credential_key = re.compile(r'(?i)(?:password|passwd|api[_-]?key|access[_-]?token|secret[_-]?key)\b')
    json_string = re.compile(r'"(?:[^"\\\r\n]|\\.){0,512}"')
    whitespace = re.compile(r'\s*')

    @classmethod
    def _unfinished_assignment(cls, text, end):
        """Inspect one bounded suffix, including whitespace across newlines.

        A dropped key with an unfinished separator/value could hide a later
        secret. Do not retain arbitrary amounts of whitespace or string data.
        Completed placeholders/non-string values remain for the normal checks.
        """
        if end < len(text) and text[end] in ('"', "'"):
            end += 1
        end = cls.whitespace.match(text, end).end()
        if end == len(text):
            return True
        if text[end] not in (':', '='):
            return False
        end = cls.whitespace.match(text, end + 1).end()
        if end == len(text):
            return True
        if text[end] not in ('"', "'"):
            return False
        quote = text[end]
        end += 1
        while end < len(text):
            if text[end] == quote:
                return False
            end += 2 if text[end] == '\\' else 1
        return True

    def _context_guard(self, text, consumed, byte_count):
        # Any unfinished context longer than the overlap would be discarded at
        # this boundary. A conservative finding is safer than accepting a prefix
        # whose value is outside the bounded window. Use Unicode whitespace as
        # the full-file recognizers do, not only ASCII byte whitespace.
        def discarded(start):
            # Surrogate escape preserves invalid original bytes; character
            # counts cannot locate a byte window boundary for Unicode text.
            offset = len(text[:start].encode('utf8', errors='surrogateescape'))
            return offset < consumed and byte_count - offset > SCAN_OVERLAP

        for match in self.credential_key.finditer(text):
            if self._unfinished_assignment(text, match.end()) and discarded(match.start()):
                self.results.add(('stream-context-limit', self.line + text.count('\n', 0, match.start())))
                return
        for match in self.json_string.finditer(text):
            try:
                key = json.loads(match[0]).lower().replace('-', '_')
            except ValueError:
                continue
            if key in ('password', 'passwd', 'api_key', 'access_token', 'secret_key', 'db_password') and self._unfinished_assignment(text, match.end()) and discarded(match.start()):
                self.results.add(('stream-context-limit', self.line + text.count('\n', 0, match.start())))
                return

    def __init__(self, size, python_source=False):
        self.small = size <= PARSE_BYTES
        self.python_source = python_source
        self.buffer = bytearray()
        self.results = set()
        self.line = 1
        self.binary = False

    def feed(self, data):
        self.binary = self.binary or b'\x00' in data
        if self.small:
            self.buffer.extend(data)
            return
        # Never let a caller's chunk size determine scanner memory or boundaries.
        for offset in range(0, len(data), SCAN_WINDOW):
            self.buffer.extend(data[offset:offset + SCAN_WINDOW])
            while len(self.buffer) >= SCAN_WINDOW * 2:
                self._window(SCAN_WINDOW)

    def _window(self, consumed):
        blob = bytes(self.buffer[:consumed + SCAN_OVERLAP])
        # Numeric CSV blocks and NUL-filled binary regions cannot contain any
        # recognizer prefix; keep the same overlap to cover adjacent text.
        if not re.search(rb'[A-Za-z./\\:"\']', blob):
            self.line += self.buffer[:consumed].count(b'\n')
            del self.buffer[:consumed]
            return
        if len(self.results) < 128:
            for rule, line in findings(blob):
                self.results.add((rule, self.line + line - 1))
                if len(self.results) >= 128:
                    self.results.add(('finding-limit', self.line))
                    break
            # Match quoted JSON key/value pairs without materializing the entire
            # object, including escaped keys and short credential values.
            # A window may end inside a multibyte whitespace character. Defer
            # that partial character instead of inserting a non-whitespace
            # replacement that would incorrectly terminate pending syntax.
            text = codecs.getincrementaldecoder('utf8')(errors='surrogateescape').decode(blob, final=False)
            self._context_guard(text, consumed, len(blob))
            for match in re.finditer(r'("(?:[^"\\]|\\.){0,512}")\s*:\s*("(?:[^"\\]|\\.){0,4096}")', text):
                try:
                    key, value = json.loads(match[1]), json.loads(match[2])
                except ValueError:
                    continue
                if key.lower().replace('-', '_') in ('password', 'passwd', 'api_key', 'access_token', 'secret_key', 'db_password'):
                    from .safety import placeholder
                    if value and not placeholder(value):
                        self.results.add(('credential-json', self.line + text.count('\n', 0, match.start())))
                if len(self.results) >= 128:
                    self.results.add(('finding-limit', self.line))
                    break
            # A long assignment/URL must not evade a regex by spanning windows.
            tail = blob.rsplit(b'\n', 1)[-1]
            if len(tail) > SCAN_OVERLAP and (self.suspicious.search(tail) or b'\\u' in tail):
                self.results.add(('stream-context-limit', self.line + blob.count(b'\n')))
        self.line += self.buffer[:consumed].count(b'\n')
        del self.buffer[:consumed]

    def finish(self):
        if self.small:
            return findings(bytes(self.buffer), python_source=self.python_source)
        self._window(len(self.buffer))
        return sorted(self.results)


@dataclass
class Snapshot:
    root: Path
    path: str
    size: int
    sha256: str
    executable: bool
    findings: list
    binary: bool
    cached: bytes | None = None

    def content(self):
        if self.size > PARSE_BYTES:
            return b''
        if self.cached is not None:
            return self.cached
        data, executable = read_safe(self.root, self.path, self.size)
        if len(data) != self.size or hashlib.sha256(data).hexdigest() != self.sha256 or executable != self.executable:
            raise ReleaseError("Source changed after inventory")
        return data


def snapshot(root, rel, size, operation=None, cache=False):
    scanner = ContentScanner(size, Path(rel).suffix.lower() in ('.py', '.pyw'))
    h = hashlib.sha256()
    with open_safe(root, rel, size) as (stream, info):
        for data in chunks(stream, size, operation, 'Scanning', rel):
            h.update(data)
            scanner.feed(data)
    result = scanner.finish()
    return Snapshot(Path(root), rel, size, h.hexdigest(), bool(info.st_mode & 0o111), result,
                    scanner.binary, bytes(scanner.buffer) if cache and scanner.small else None)
