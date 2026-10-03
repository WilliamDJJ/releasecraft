"""Filesystem boundaries, bounded reads, and redacted content checks."""

from __future__ import annotations
import hashlib
from contextlib import contextmanager
import ast
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile


class ReleaseError(Exception):
    """A release operation cannot safely proceed."""


def canonical(value):
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def atomic_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".releasecraft-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def relative(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ReleaseError("Invalid relative path")
    p = PurePosixPath(value)
    if p.is_absolute() or any(x in ("", ".", "..") for x in value.split("/")):
        raise ReleaseError("Unsafe relative path")
    for part in p.parts:
        if (
            any(c in part for c in ':"<>|?*')
            or part[-1:] in (".", " ")
            or any(ord(c) < 32 for c in part)
        ):
            raise ReleaseError("Nonportable path")
        if part.split(".")[0].upper() in {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            *(f"COM{i}" for i in range(1, 10)),
            *(f"LPT{i}" for i in range(1, 10)),
        }:
            raise ReleaseError("Windows reserved path")
    return value


def separate(source, output):
    a, b = Path(source).resolve(), Path(output).resolve()
    if a == b or a in b.parents or b in a.parents:
        raise ReleaseError("Source and work/output paths must be disjoint")


def linked(path):
    st = path.lstat()
    return stat.S_ISLNK(st.st_mode) or bool(
        getattr(st, "st_file_attributes", 0) & 0x400
    )


@contextmanager
def open_safe(root, rel, limit=None):
    relative(rel)
    root = Path(root).absolute()
    if os.name == "nt":
        from .windows import open_locked

        with open_locked(root, rel, limit) as opened:
            yield opened
        return
    path = root
    for part in PurePosixPath(rel).parts:
        path /= part
        if linked(path):
            raise ReleaseError("Links and reparse points are not followed")
    before = path.stat()
    if not stat.S_ISREG(before.st_mode):
        raise ReleaseError("Only regular files are supported")
    if before.st_nlink > 1:
        raise ReleaseError("Hard-linked files require an independent copy")
    if limit is not None and before.st_size > limit:
        raise ReleaseError("File exceeds bounded scan limit")
    if os.name == "posix":
        directory = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            parts = PurePosixPath(rel).parts
            for part in parts[:-1]:
                nxt = os.open(
                    part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory
                )
                os.close(directory)
                directory = nxt
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=directory)
        finally:
            os.close(directory)
    else:
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    with os.fdopen(fd, "rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns, opened.st_ctime_ns) != (
            before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns
        ) or opened.st_nlink != 1:
            raise ReleaseError("Source changed before read")
        yield stream, opened
        after = os.fstat(stream.fileno())
    end = path.stat()

    def identity(x):
        return (x.st_dev, x.st_ino, x.st_size, x.st_mtime_ns, x.st_ctime_ns)

    if (
        identity(before) != identity(opened)
        or identity(opened) != identity(after)
        or identity(after) != identity(end)
    ):
        raise ReleaseError("Source changed during read")


def read_safe(root, rel, limit=16 * 1024 * 1024):
    with open_safe(root, rel, limit) as (stream, before):
        data = stream.read(limit + 1)
        if len(data) > limit:
            raise ReleaseError("Source changed during read")
    return data, bool(before.st_mode & 0o111)


# Values are never included in findings. Conservative recognizers are not a DLP guarantee.
_PATTERNS = {
    "private-key": r"-----BEGIN (?:RSA |EC |OPENSSH |DSA )?PRIVATE KEY-----",
    "provider-token": r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{20,}|xox[baprs]-[A-Za-z0-9-]{16,})",
    "credential-assignment": r"""(?i)["']?(?:password|passwd|api[_-]?key|access[_-]?token|secret[_-]?key)["']?\s*[:=]\s*["']([^"'\r\n]{8,})["']""",
    "credential-url": r"(?i)(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|https?)://[^\s/:]+:[^\s/@]+@",
    "npm-credential-assignment": r"""(?im)^[ \t]*(?:[;#][ \t]*)?(?://[^\s=\r\n]+:)?["']?(?:_?auth(?:[-_]?token)?|_password|npm_token|node_auth_token)["']?[ \t]*=[ \t]*["']?([^"'\s#;]+)""",
    "personal-path": r"(?:/"
    + r'Users/[^\s/"\']+|/'
    + r'home/(?!runner\b)[^\s/"\']+|[A-Za-z]:\\Users\\[^\s\\"\']+)',
    "private-address": r"\b(?:10\.(?:\d{1,3}\.){2}\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b",
}


def placeholder(value):
    return value.startswith(("${", "<", "YOUR_", "EXAMPLE_", "REPLACE_")) or value in (
        "changeme",
        "placeholder",
    )


def npm_preferences(data):
    """Recognize literal npm preferences, never expand or execute configuration.

    This is a small publication subset, not an npm/ini implementation. All bytes
    still require ordinary content scanning, including full-line comments.
    """
    if len(data) > 65536:
        return False
    try:
        text = data.decode("utf-8").replace("\r\n", "\n")
    except UnicodeDecodeError:
        return False
    if any((ord(c) < 32 and c not in "\t\n") or ord(c) == 127 for c in text):
        return False
    lines = text.split("\n")
    if lines[-1] == "":
        lines.pop()
    if len(lines) > 256:
        return False
    boolean_keys = {
        "package-lock", "package-lock-only", "format-package-lock", "save-exact",
        "fund", "progress", "color", "unicode", "engine-strict", "prefer-dedupe",
    }
    seen = set()
    for raw in lines:
        line = raw.strip(" \t")
        if not line:
            continue
        if line.startswith(("#", ";")):
            # Commented credentials, endpoints or substitutions still need review.
            if any(marker in line for marker in ("=", "://", "${")):
                return False
            continue
        if line.count("=") != 1:
            return False
        key, value = (part.strip(" \t") for part in line.split("=", 1))
        if key in seen:
            return False
        seen.add(key)
        if key in boolean_keys and value in ("true", "false"):
            continue
        if key == "lockfile-version" and value in ("1", "2", "3"):
            continue
        return False
    return True


def _python_reference_lines(text):
    """Recognize parameter references and environment lookups, never evaluate code.

    Only the unquoted environment-assignment heuristic uses this context. Raw
    token, key, URL, literal-assignment and private-path checks still scan every
    byte. Unknown names, syntax errors and oversized trees stay conservative.
    """
    if len(text) > 1024 * 1024:
        return set()
    try:
        tree = ast.parse(text)
        nodes = []
        for node in ast.walk(tree):
            nodes.append(node)
            if len(nodes) > 100000:
                return set()
    except (SyntaxError, ValueError, RecursionError):
        return set()
    imports = {}
    shadowed = set()
    import_counts = {}
    for node in nodes:
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadowed.add(node.id)
        elif isinstance(node, ast.arg):
            shadowed.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            shadowed.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for item in node.names:
                name = item.asname or item.name.split('.')[0]
                import_counts[name] = import_counts.get(name, 0) + 1
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)):
            shadowed.add(ast.unparse(node).split('.')[0])
    if any(isinstance(n, ast.ImportFrom) and any(a.name == '*' for a in n.names) for n in nodes):
        return set()
    for node in tree.body:
        if isinstance(node, ast.Import):
            imports.update({a.asname or a.name.split('.')[0]: a.name for a in node.names})
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.update({a.asname or a.name: node.module + '.' + a.name for a in node.names})
    imports = {name: target for name, target in imports.items() if name not in shadowed and import_counts.get(name) == 1}

    def qualified(node):
        if isinstance(node, ast.Name):
            return imports.get(node.id, '')
        if isinstance(node, ast.Attribute):
            base = qualified(node.value)
            return base + '.' + node.attr if base else ''
        return ''

    def key(node):
        return isinstance(node, ast.Constant) and isinstance(node.value, str) and bool(re.fullmatch(r'[A-Z_][A-Z0-9_]*', node.value))

    def reference(node, parameters):
        if isinstance(node, ast.Name):
            return node.id in parameters
        if isinstance(node, ast.Attribute):
            return reference(node.value, parameters)
        if isinstance(node, ast.Subscript):
            if qualified(node.value) == 'os.environ' and key(node.slice):
                return True
            index = node.slice
            if isinstance(index, ast.UnaryOp) and isinstance(index.op, (ast.USub, ast.UAdd)):
                index = index.operand
            return reference(node.value, parameters) and isinstance(index, ast.Constant) and type(index.value) is int
        if isinstance(node, ast.Call):
            if qualified(node.func) in ('os.getenv', 'os.environ.get'):
                return len(node.args) == 1 and not node.keywords and key(node.args[0])
            known = (isinstance(node.func, ast.Name) and node.func.id in (set(imports) | ({'str','bytes','int'} - shadowed))) or (isinstance(node.func, ast.Attribute) and reference(node.func, parameters))
            return bool(known and not node.keywords and node.args and all(reference(arg, parameters) for arg in node.args))
        return False

    statement_lines = {}
    for node in nodes:
        if isinstance(node, ast.stmt):
            statement_lines[node.lineno] = statement_lines.get(node.lineno, 0) + 1
    lines = set()
    pending = [(tree, set())]
    try:
        while pending:
            node, parameters = pending.pop()
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                arguments = node.args
                declared = {a.arg for a in (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)}
                declared |= {a.arg for a in (arguments.vararg, arguments.kwarg) if a is not None}
                parameters = (parameters - declared) | declared
                positional = [*arguments.posonlyargs, *arguments.args]
                defaults = list(zip(positional[len(positional)-len(arguments.defaults):], arguments.defaults))
                defaults += list(zip(arguments.kwonlyargs, arguments.kw_defaults))
                parameters -= {a.arg for a, default in defaults if default is not None and not (isinstance(default, ast.Constant) and default.value is None)}
                # Rebinding to an unknown/literal value invalidates provenance.
                # Fixed-point removal also covers chains and nested shadowing,
                # without attempting runtime control-flow evaluation.
                scope = list(ast.walk(node))
                while True:
                    invalid = set()
                    for item in scope:
                        if isinstance(item, (ast.Assign, ast.AnnAssign)):
                            targets = item.targets if isinstance(item, ast.Assign) else [item.target]
                            if not reference(item.value, parameters):
                                invalid.update(n.id for target in targets for n in ast.walk(target) if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))
                        elif isinstance(item, (ast.AugAssign, ast.NamedExpr)):
                            invalid.update(n.id for n in ast.walk(item.target) if isinstance(n, ast.Name))
                        elif isinstance(item, (ast.For, ast.AsyncFor, ast.comprehension)):
                            invalid.update(n.id for n in ast.walk(item.target) if isinstance(n, ast.Name))
                        elif isinstance(item, ast.withitem) and item.optional_vars is not None:
                            invalid.update(n.id for n in ast.walk(item.optional_vars) if isinstance(n, ast.Name))
                        elif isinstance(item, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
                            invalid.add(item.name)
                        elif isinstance(item, ast.MatchMapping):
                            invalid.add(item.rest)
                    retained = parameters - invalid
                    if retained == parameters:
                        break
                    parameters = retained
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                if statement_lines.get(node.lineno) == 1 and all(isinstance(target, ast.Name) for target in targets) and reference(node.value, parameters):
                    lines.add(node.lineno)
            pending.extend((child, parameters) for child in ast.iter_child_nodes(node))
    except RecursionError:
        return set()
    return lines


def findings(data, *, python_source=False):
    text = data.decode("utf-8", errors="replace")
    found = []
    for rule, pattern in _PATTERNS.items():
        cursor = 0
        line = 1
        for m in re.finditer(pattern, text):
            line += text.count("\n", cursor, m.start())
            cursor = m.start()
            if rule in ("credential-assignment", "npm-credential-assignment"):
                value = m.group(1)
                if value.startswith(
                    ("${", "<", "YOUR_", "EXAMPLE_", "REPLACE_")
                ) or value in ("changeme", "placeholder"):
                    continue
            found.append({"rule": rule, "line": line})
            if len(found) >= 128:
                return sorted(
                    {(x["rule"], x["line"]) for x in found} | {("finding-limit", line)}
                )
    env_cursor = 0
    env_line = 1
    environment_pattern = r"(?im)^[ \t]*(?:export[ \t]+)?(?:DB_PASSWORD|PASSWORD|PASSWD|API_KEY|ACCESS_TOKEN|SECRET_KEY)[ \t]*=[ \t]*([^\s\"\'#]+)"
    reference_lines = _python_reference_lines(text) if python_source and re.search(environment_pattern, text) else set()
    for m in re.finditer(environment_pattern, text):
        env_line += text.count("\n", env_cursor, m.start())
        env_cursor = m.start()
        if len(found) >= 128:
            return sorted(
                {(x["rule"], x["line"]) for x in found} | {("finding-limit", env_line)}
            )
        if env_line not in reference_lines and not placeholder(m.group(1)):
            found.append(
                {
                    "rule": "credential-environment",
                    "line": env_line,
                }
            )
    try:
        value = json.loads(text)
        stack = [value]
        visited = 0
        while stack:
            visited += 1
            if visited > 100000 or len(found) >= 128:
                found.append({"rule": "scan-structure-limit", "line": 1})
                break
            item = stack.pop()
            if isinstance(item, dict):
                for key, val in item.items():
                    if (
                        str(key).lower().replace("-", "_")
                        in (
                            "password",
                            "passwd",
                            "api_key",
                            "access_token",
                            "secret_key",
                            "db_password",
                        )
                        and isinstance(val, str)
                        and val
                        and not placeholder(val)
                    ):
                        found.append({"rule": "credential-json", "line": 1})
                        if len(found) >= 128:
                            return sorted(
                                {(x["rule"], x["line"]) for x in found}
                                | {("finding-limit", 1)}
                            )
                    if isinstance(val, (dict, list)):
                        stack.append(val)
            elif isinstance(item, list):
                stack.extend(item)
    except ValueError:
        pass
    except RecursionError:
        found.append({"rule": "scan-depth-limit", "line": 1})
    return sorted({(x["rule"], x["line"]) for x in found})


def safe_notebook(data):
    obj = json.loads(data)
    if (
        not isinstance(obj, dict)
        or obj.get("nbformat") != 4
        or not isinstance(obj.get("cells"), list)
    ):
        raise ReleaseError("Unsupported Notebook schema")
    for cell in obj["cells"]:
        if not isinstance(cell, dict) or cell.get("cell_type") not in (
            "code",
            "markdown",
            "raw",
        ):
            raise ReleaseError("Invalid Notebook cell")
        if cell.get("cell_type") == "code":
            cell["outputs"] = []
            cell["execution_count"] = None
    # Metadata can control execution (for example parameter tags); preserve it and
    # source attachments. Remaining sensitive content is checked after transformation.
    return canonical(obj)
