"""Conservative static analysis and replayable per-file decisions."""

from __future__ import annotations
import ast
import fnmatch
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tomllib
from urllib.parse import unquote
from .policy import VERSION, load_policy
from . import __version__
from .streaming import snapshot, PARSE_BYTES, CACHE_BYTES
from .operation import signal
from .diagnostics import EvidenceBudget, EvidenceLimit, blocker_summary
from .native import resource_edges
from .residue import context_rule, playwright_context, agent_config_safe
from .documentation import draft_readme
from .safety import (
    ReleaseError,
    atomic_json,
    canonical,
    digest,
    findings,
    linked,
    npm_preferences,
    relative,
    safe_notebook,
    separate,
)

PRUNED = {
    ".git",
    ".hg",
    ".svn",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".releasecraft",
}
SOURCE = {
    ".py",
    ".pyw",
    ".pyi",
    ".js",
    ".mjs",
    ".cjs",
    ".ts",
    ".tsx",
    ".jsx",
    ".html",
    ".css",
    ".sh",
    ".ps1",
    ".bat",
    ".cmd",
    ".ipynb",
}
DOC = {".md", ".rst", ".txt"}
META = {
    "pyproject.toml",
    "setup.cfg",
    "setup.py",
    "MANIFEST.in",
    "package.json",
    "package-lock.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "uv.lock",
    "poetry.lock",
    "requirements.txt",
    "requirements-dev.txt",
    "tsconfig.json",
    "Dockerfile",
    "Makefile",
    ".gitignore",
    ".gitattributes",
    ".npmignore",
    ".editorconfig",
}
TRANSIENT = {".log", ".pyc", ".pyo", ".tmp", ".bak", ".orig"}
MAINTENANCE = {".travis.yml", ".travis.yaml", ".eslintrc.json", "tox.ini", "CITATION.cff"}


def match(path, patterns):
    return any(
        fnmatch.fnmatchcase(path, p)
        or (p.endswith("/**") and path.startswith(p[:-3] + "/"))
        for p in patterns
    )


MAX_SCAN_ENTRIES = 20000
MAX_DIRECTORY_ENTRIES = 4096
MAX_SCAN_BYTES = None  # Optional operator budget; no fixed project byte cap.
MAX_INVENTORY_ERRORS = 1000
MAX_SCAN_DEPTH = 64
MAX_ANALYSIS_EVIDENCE = 20000


def inventory(root, limit=None, *, audit=None, operation=None, byte_limit=None):
    """Bounded deterministic traversal; one lookahead entry may detect overflow.

    Every directory entry observed counts, including invalid/unreadable entries.
    An overflowing directory is not partially processed in filesystem order.
    Read reservations include read_safe's one-byte mutation-detection lookahead
    and are never refunded after an error: they bound possible reads, not just
    retained successful payloads. No actual byte-volume claim is made for errors.
    """
    root = Path(root).resolve()
    files, ignored, errors = {}, [], []
    seen = set()
    cache_remaining = CACHE_BYTES
    byte_limit = MAX_SCAN_BYTES if byte_limit is None else byte_limit
    scan = {
        "complete": True,
        "traversal_complete": True,
        "stop_reason": None,
        "entries_observed": 0,
        "entries_processed": 0,
        "directories_enumerated": 0,
        "pruned_directories": 0,
        "regular_files_seen": 0,
        "read_attempts": 0,
        "files_read": 0,
        "bytes_reserved": 0,
        "bytes_retained": 0,
        "errors_observed": 0,
        "error_details_omitted_at_least": 0,
        "limits": {
            "entries": MAX_SCAN_ENTRIES,
            "directory_entries": MAX_DIRECTORY_ENTRIES,
            "bytes_reserved": byte_limit,
            "parser_bytes_per_file": PARSE_BYTES,
            "payload_cache_bytes": CACHE_BYTES,
            "error_details": MAX_INVENTORY_ERRORS,
            "depth": MAX_SCAN_DEPTH,
            "enumeration_lookahead_entries": 1,
        },
    }

    class StopScan(Exception):
        pass

    def stop(code):
        scan.update(complete=False, traversal_complete=False, stop_reason=code)
        # One reserved terminal diagnostic sits outside the ordinary error cap.
        errors.append({"code": code, "inventory_complete": False})
        raise StopScan()

    def error(code, rel, exc):
        scan["complete"] = False
        scan["errors_observed"] += 1
        if scan["errors_observed"] > MAX_INVENTORY_ERRORS:
            scan["error_details_omitted_at_least"] += 1
            stop("scan-diagnostic-limit")
        errors.append({
            "code": code,
            "path_id": digest(rel.encode())[:16],
            "reason": type(exc).__name__,
        })

    def entries(directory):
        rel = directory.relative_to(root).as_posix()
        collected = []
        try:
            if linked(directory):
                raise ReleaseError("Link or reparse point")
            with os.scandir(directory) as iterator:
                scan["directories_enumerated"] += 1
                for entry in iterator:
                    scan["entries_observed"] += 1
                    if scan["entries_observed"] > MAX_SCAN_ENTRIES:
                        stop("scan-entry-limit")
                    if len(collected) >= MAX_DIRECTORY_ENTRIES:
                        stop("scan-directory-entry-limit")
                    collected.append(entry)
        except (OSError, ReleaseError) as exc:
            # Discard an incomplete, order-dependent directory enumeration.
            scan["traversal_complete"] = False
            error("unreadable-directory", rel, exc)
            return []
        return sorted(collected, key=lambda entry: entry.name)

    pending = [(root, 0)]
    try:
        while pending:
            directory, depth = pending.pop()
            children = []
            for entry in entries(directory):
                signal(operation, "Scanning", current=entry.name, files=scan["files_read"], bytes_read=scan["bytes_retained"], total_files=None)
                scan["entries_processed"] += 1
                path = Path(entry.path)
                rel = path.relative_to(root).as_posix()
                try:
                    relative(rel)
                    folded = rel.casefold()
                    if folded in seen:
                        raise ReleaseError("Case-insensitive path collision")
                    seen.add(folded)
                    info = entry.stat(follow_symlinks=False)
                    if stat.S_ISLNK(info.st_mode) or (
                        getattr(info, "st_file_attributes", 0) & 0x400
                    ):
                        raise ReleaseError("Link or reparse point")
                    if stat.S_ISDIR(info.st_mode):
                        managed = False
                        if entry.name == "releasecraft-output":
                            from .managed import owned_output
                            managed = owned_output(path, root, getattr(operation, "state_directory", None))
                            if not managed:
                                raise ReleaseError("Unowned reserved output directory")
                        if managed or rel == ".claude/worktrees" or entry.name in PRUNED or entry.name.endswith(".egg-info"):
                            scan["pruned_directories"] += 1
                            ignored.append({
                                "path": rel,
                                "state": "EXCLUDE",
                                "reason": "owned-releasecraft-output" if managed else "parallel-agent-checkouts" if rel == ".claude/worktrees" else "tool-cache-directory",
                                "sha256": None,
                                "size": 0,
                                "executable": False,
                                "kind": "directory",
                            })
                        else:
                            if depth >= MAX_SCAN_DEPTH:
                                stop("scan-depth-limit")
                            children.append((path, depth + 1))
                    elif stat.S_ISREG(info.st_mode):
                        scan["regular_files_seen"] += 1
                        size = info.st_size
                        if size < 0 or (limit is not None and size > limit) or info.st_nlink > 1:
                            raise ReleaseError("Unsafe file or per-file size limit")
                        reservation = size + 1
                        if byte_limit is not None and reservation > byte_limit - scan["bytes_reserved"]:
                            stop("scan-byte-limit")
                        scan["bytes_reserved"] += reservation
                        scan["read_attempts"] += 1
                        item = snapshot(root, rel, size, operation, cache=size <= cache_remaining)
                        if item.cached is not None:
                            cache_remaining -= len(item.cached)
                        scan["bytes_retained"] += item.size
                        scan["files_read"] += 1
                        files[rel] = item
                    else:
                        raise ReleaseError("Special file")
                except (OSError, ReleaseError) as exc:
                    error("unsafe-or-unreadable-file", rel, exc)
            # Iterative traversal avoids Python recursion and preserves name order.
            pending.extend(reversed(children))
    except StopScan:
        pass
    scan["error_details_retained"] = min(scan["errors_observed"], MAX_INVENTORY_ERRORS)
    if audit is not None:
        audit.update(scan)
    return files, ignored, errors


def dependencies(path, data, paths, policy, evidence=None, local_functions=None):
    """Return exact edges, unresolved references, and import metadata."""
    edges = evidence["edges"] if evidence is not None else []
    unknown = evidence["unresolved"] if evidence is not None else []
    imports = evidence["imports"] if evidence is not None else []
    suffix = PurePosixPath(path).suffix
    text = data.decode("utf-8", errors="replace")
    resource_files = set()

    def resolve(value, kind, required=True, file_relative=False, generated=False):
        if (
            not isinstance(value, str)
            or not value
            or "://" in value
            or (kind == "document-resource" and value.startswith("#"))
        ):
            return
        if kind in ("document-resource", "js-import", "js-url-resource"):
            value = value.split("#")[0].split("?")[0]
        if kind == "document-resource":
            # GitHub resolves these Markdown links against its repository UI,
            # not files in the release. Do not generalize to arbitrary traversal.
            prefix = "../" * (len(PurePosixPath(path).parent.parts) + 2)
            if value.startswith(prefix) and re.fullmatch(
                r"(?:issues(?:/(?:new|[1-9][0-9]*))?|pull/[1-9][0-9]*|discussions(?:/[1-9][0-9]*)?)",
                value[len(prefix):],
            ):
                return
        if kind == "js-url-resource":
            value = unquote(value)
        if value.startswith(("/", "~")) or re.match(r"^[A-Za-z]:", value):
            unknown.append({"code": "absolute-resource", "evidence": kind})
            return
        candidates = []
        bases = (PurePosixPath(path).parent,) if file_relative else (PurePosixPath(path).parent, PurePosixPath("."))
        for base in bases:
            joined = os.path.normpath(str(base / value)).replace("\\", "/")
            if joined.startswith("../"):
                continue
            candidates.append(joined)
        hits = [v for v in candidates if v in paths]
        if not hits and kind in ("js-import", "python-import"):
            for c in candidates:
                hits += [
                    os.path.normpath(v).replace("\\", "/")
                    for v in (
                        c + ".py",
                        c + "/__init__.py",
                        c + ".js",
                        c + ".ts",
                        c + ".tsx",
                        c + "/index.js",
                        c + "/index.ts",
                    )
                    if os.path.normpath(v).replace("\\", "/") in paths
                ]
        if hits:
            for hit in sorted(set(hits)):
                edges.append({"target": hit, "kind": kind})
        elif required and not generated and value not in policy["external"]:
            unknown.append(
                {"code": "missing-resource", "reference": value, "evidence": kind}
            )

    literal_bindings = {}

    def literal_path(node):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return node.value
        if isinstance(node, ast.Name) and node.id == "__file__":
            return path
        if isinstance(node, ast.Name) and node.id in literal_bindings:
            value, assigned_at = literal_bindings[node.id]
            if node.lineno > assigned_at:
                return value
            return None
        if isinstance(node, ast.Attribute) and node.attr == "parent":
            base = literal_path(node.value)
            if base is not None:
                return str(PurePosixPath(base).parent)
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
            a, b = literal_path(node.left), literal_path(node.right)
            if a is not None and b is not None:
                return str(PurePosixPath(a) / b)
        if isinstance(node, ast.Call):
            if ast.unparse(node.func) in resource_files:
                values = node.args + [k.value for k in node.keywords if k.arg in ("anchor", "package")]
                anchor = values[0] if len(values) == 1 and all(k.arg in ("anchor", "package") for k in node.keywords) else None
                if isinstance(anchor, ast.Constant) and isinstance(anchor.value, str) and all(p.isidentifier() for p in anchor.value.split(".")):
                    suffix = anchor.value.replace(".", "/") + "/__init__.py"
                    matches = [p for p in paths if p == suffix or p.endswith("/" + suffix)]
                    if len(matches) == 1:
                        return str(PurePosixPath(matches[0]).parent)
                return None
            if ast.unparse(node.func) in ("Path", "pathlib.Path") and node.args:
                parts = [literal_path(a) for a in node.args]
                if all(part is not None for part in parts):
                    return str(PurePosixPath(*parts))
                return None
            if isinstance(node.func, ast.Attribute):
                base = literal_path(node.func.value)
                parts = [literal_path(a) for a in node.args]
                if base is not None and all(x is not None for x in parts):
                    if node.func.attr == "with_name" and len(parts) == 1:
                        return str(PurePosixPath(base).with_name(parts[0]))
                    if node.func.attr == "joinpath":
                        return str(PurePosixPath(base).joinpath(*parts))
                    if node.func.attr == "resolve" and not parts:
                        return base
        return None

    def open_argument(node, position, keyword, default=None):
        # Expanded or duplicate arguments cannot establish a literal binding.
        if any(isinstance(a, ast.Starred) for a in node.args) or any(
            k.arg is None for k in node.keywords
        ):
            return None
        values = node.args[position : position + 1] + [
            k.value for k in node.keywords if k.arg == keyword
        ]
        return values[0] if len(values) == 1 else default if not values else None

    def open_mode(node):
        if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
            return None
        mode = node.value
        # Only valid literal modes can prove that an existing input is unnecessary.
        if (
            not mode
            or set(mode) - set("rwaxbt+")
            or len(mode) != len(set(mode))
            or sum(c in mode for c in "rwax") != 1
            or ("b" in mode and "t" in mode)
        ):
            return None
        return "write" if any(c in mode for c in "wax") else "read"

    if suffix == ".ipynb":
        try:
            nb = json.loads(text)
            text = "\n".join(
                "".join(c.get("source", []))
                for c in nb.get("cells", [])
                if c.get("cell_type") == "code"
            )
        except (ValueError, TypeError):
            unknown.append({"code": "invalid-notebook"})
    if suffix in (".py", ".pyw", ".pyi", ".ipynb"):
        try:
            tree = ast.parse(text)
        except SyntaxError:
            unknown.append({"code": "python-syntax-or-notebook-magic"})
            tree = None
        if tree:
            # Only imported resource APIs establish package anchors. A shadowed
            # binding stays dynamic; no project module is imported or executed.
            aliases = set()
            import_aliases = set()
            bindings = {}
            wildcard_import = False
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for item in node.names:
                        binding = item.asname or item.name.split(".")[0]
                        bindings.setdefault(binding, set()).add(item.name if item.asname else item.name.split(".")[0])
                        if item.name == "importlib.resources":
                            aliases.add((item.asname or item.name) + ".files")
                        elif item.name == "importlib":
                            aliases.add((item.asname or item.name) + ".resources.files")
                            import_aliases.add((item.asname or item.name) + ".import_module")
                elif isinstance(node, ast.ImportFrom):
                    for item in node.names:
                        wildcard_import |= item.name == "*"
                        bindings.setdefault(item.asname or item.name, set()).add((node.module or "") + "." + item.name)
                        if node.module == "importlib.resources" and item.name == "files":
                            aliases.add(item.asname or item.name)
                        elif node.module == "importlib" and item.name == "resources":
                            aliases.add((item.asname or item.name) + ".files")
                        elif node.module == "importlib" and not node.level and item.name == "import_module":
                            import_aliases.add(item.asname or item.name)
            shadowed = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del))}
            shadowed.update(node.arg for node in ast.walk(tree) if isinstance(node, ast.arg))
            shadowed.update(node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)))
            shadowed.update(node.name for node in ast.walk(tree) if isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)))
            shadowed.update(node.rest for node in ast.walk(tree) if isinstance(node, ast.MatchMapping))
            shadowed.update(name for name, targets in bindings.items() if len(targets) > 1)
            shadowed.update(ast.unparse(node).split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Attribute) and isinstance(node.ctx, (ast.Store, ast.Del)))
            # Local module-level functions are analyzed at their definitions.
            # A name such as load() alone does not establish a third-party I/O API.
            # Reexports, ambiguous imports, rebinding and parameter shadowing keep
            # the existing conservative heuristic; no source module is executed.
            local_calls = set()
            if local_functions is not None and not wildcard_import:
                function_defs = [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.decorator_list]
                all_definitions = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
                other_stores = {n.id for n in ast.walk(tree) if isinstance(n, ast.Name) and isinstance(n.ctx, (ast.Store, ast.Del))}
                other_stores.update(n.arg for n in ast.walk(tree) if isinstance(n, ast.arg))
                other_stores.update(n.name for n in ast.walk(tree) if isinstance(n, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)))
                other_stores.update(n.rest for n in ast.walk(tree) if isinstance(n, ast.MatchMapping))
                local_calls.update(name for name in function_defs if all_definitions.count(name) == 1 and name not in other_stores and name not in bindings)

                def module_files(module, level=0):
                    roots = ["", "src/"]
                    if level:
                        parent = PurePosixPath(path).parent
                        for _ in range(level - 1):
                            parent = parent.parent
                        roots = [str(parent) + "/"]
                    rel = module.replace(".", "/")
                    return [candidate for root in roots for candidate in (root + rel + ".py", root + rel + "/__init__.py") if candidate in paths]

                for statement in tree.body:
                    if isinstance(statement, ast.ImportFrom) and statement.module:
                        candidates = module_files(statement.module, statement.level)
                        if len(candidates) == 1:
                            functions = local_functions(candidates[0])
                            local_calls.update(item.asname or item.name for item in statement.names if item.name in functions and (item.asname or item.name) not in shadowed)
                    elif isinstance(statement, ast.Import):
                        for item in statement.names:
                            alias = item.asname or item.name
                            if alias.split(".")[0] in shadowed:
                                continue
                            candidates = module_files(item.name)
                            if len(candidates) == 1:
                                local_calls.update(alias + "." + function for function in local_functions(candidates[0]))
            if not wildcard_import:
                resource_files.update(name for name in aliases if name.split(".")[0] not in shadowed)
            import_calls = {name for name in import_aliases if not wildcard_import and name.split(".")[0] not in shadowed}
            # Only one direct module-level string assignment establishes a path
            # constant. No evaluation, alias propagation or conditional dataflow.
            stores = {}
            ambiguous = set(bindings)
            for node in ast.walk(tree):
                if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                    stores[node.id] = stores.get(node.id, 0) + 1
                elif isinstance(node, ast.arg):
                    ambiguous.add(node.arg)
                elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
                    ambiguous.add(node.name)
                elif isinstance(node, ast.MatchMapping):
                    ambiguous.add(node.rest)
            if not wildcard_import:
                for statement in tree.body:
                    targets = statement.targets if isinstance(statement, ast.Assign) else [statement.target] if isinstance(statement, ast.AnnAssign) else []
                    value = getattr(statement, "value", None)
                    if len(targets) != 1 or not isinstance(targets[0], ast.Name) or not isinstance(value, ast.Constant) or not isinstance(value.value, str):
                        continue
                    name = targets[0].id
                    if stores.get(name) == 1 and name not in ambiguous:
                        literal_bindings[name] = (value.value, statement.end_lineno)
            # Prove only an immediate, straight-line create-then-read idiom.
            # No function/control-flow inference: conditional writers, intervening
            # calls, shadowed APIs and existing source files retain their gates.
            generated_reads = set()
            builtin_open = not wildcard_import and "open" not in shadowed and "open" not in bindings
            plain_json = bindings.get("json") == {"json"} and "json" not in shadowed
            for writer, reader in zip(tree.body, tree.body[1:]):
                if not builtin_open or not isinstance(writer, ast.With) or len(writer.items) != 1:
                    continue
                item = writer.items[0]
                call = item.context_expr
                if not isinstance(call, ast.Call) or ast.unparse(call.func) != "open" or not isinstance(item.optional_vars, ast.Name):
                    continue
                value = literal_path(open_argument(call, 0, "file"))
                if value is None or open_mode(open_argument(call, 1, "mode", ast.Constant("r"))) != "write":
                    continue
                allowed_writes = {item.optional_vars.id + ".write"}
                if plain_json:
                    allowed_writes.add("json.dump")
                if not all(isinstance(statement, ast.Pass) or isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Call) for statement in writer.body):
                    continue
                if any(isinstance(node, ast.Call) and ast.unparse(node.func) not in allowed_writes for statement in writer.body for node in ast.walk(statement)):
                    continue
                if isinstance(reader, ast.With):
                    if len(reader.items) != 1:
                        continue
                    reading = reader.items[0].context_expr
                    if (not isinstance(reading, ast.Call) or ast.unparse(reading.func) != "open"
                            or literal_path(open_argument(reading, 0, "file")) != value
                            or not all(isinstance(statement, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Assert, ast.Pass)) for statement in reader.body)):
                        continue
                elif not isinstance(reader, (ast.Expr, ast.Assign, ast.AnnAssign, ast.Assert)):
                    continue
                reader_nodes = list(ast.walk(reader))
                if any(isinstance(node, (ast.Lambda, ast.GeneratorExp, ast.ListComp, ast.SetComp, ast.DictComp, ast.NamedExpr)) for node in reader_nodes):
                    continue
                allowed_reads = {"open"} | ({"json.load", "json.loads"} if plain_json else set())
                if any(isinstance(node, ast.Call) and ast.unparse(node.func) not in allowed_reads for node in reader_nodes):
                    continue
                generated_reads.update(id(node) for node in reader_nodes if isinstance(node, ast.Call) and ast.unparse(node.func) == "open" and literal_path(open_argument(node, 0, "file")) == value)
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    names = (
                        [a.name for a in node.names]
                        if isinstance(node, ast.Import)
                        else (
                            [node.module]
                            if node.module
                            else [a.name for a in node.names]
                        )
                    )
                    for name in names:
                        if not name:
                            continue
                        imports.append(name.split(".")[0])
                        relname = name.replace(".", "/")
                        roots = ["", "src/"]
                        if isinstance(node, ast.ImportFrom) and node.level:
                            parent = PurePosixPath(path).parent
                            for _ in range(node.level - 1):
                                parent = parent.parent
                            roots = [str(parent) + "/"]
                        for root in roots:
                            for candidate in (
                                root + relname + ".py",
                                root + relname + "/__init__.py",
                            ):
                                if candidate in paths:
                                    edges.append(
                                        {"target": candidate, "kind": "python-import"}
                                    )
                if isinstance(node, ast.Call):
                    name = ast.unparse(node.func)
                    leaf = name.split(".")[-1]
                    root_name, _, tail = name.partition('.')
                    targets = bindings.get(root_name, set())
                    reader_name = name
                    if len(targets) == 1:
                        reader_name = next(iter(targets)) + ('.' + tail if tail else '')
                    reader_leaf = reader_name.split('.')[-1]
                    import_call = name in import_aliases or leaf in ("import_module", "__import__")
                    if import_call:
                        argument = open_argument(node, 0, "name")
                        if (
                            (name not in import_aliases or name in import_calls)
                            and isinstance(argument, ast.Constant)
                            and isinstance(argument.value, str)
                        ):
                            module = argument.value.replace(".", "/")
                            found = [
                                x
                                for x in (
                                    module + ".py",
                                    "src/" + module + ".py",
                                    module + "/__init__.py",
                                    "src/" + module + "/__init__.py",
                                )
                                if x in paths
                            ]
                            if found:
                                edges.extend(
                                    {"target": x, "kind": "dynamic-import-literal"}
                                    for x in found
                                )
                            else:
                                imports.append(argument.value)
                        elif (
                            path not in policy["dynamic_resources"]
                            and path not in policy["reviewed_dynamic"]
                        ):
                            unknown.append(
                                {"code": "dynamic-import", "line": node.lineno}
                            )
                    if leaf == "open":
                        pathlib_open = isinstance(
                            node.func, ast.Attribute
                        ) and name not in ("io.open", "builtins.open")
                        resource_code = (
                            "dynamic-pathlib-resource" if pathlib_open else "dynamic-resource"
                        )
                        kind = "pathlib-open" if pathlib_open else "runtime-read"
                        value = literal_path(
                            node.func.value
                            if pathlib_open
                            else open_argument(node, 0, "file")
                        )
                        mode = open_mode(
                            open_argument(
                                node, 0 if pathlib_open else 1, "mode", ast.Constant("r")
                            )
                        )
                        reviewed = (
                            path in policy["reviewed_dynamic"]
                            or path in policy["dynamic_resources"]
                        )
                        if mode is None and not reviewed:
                            unknown.append(
                                {"code": "dynamic-open-mode", "line": node.lineno}
                            )
                        if value is not None:
                            if mode != "write":
                                resolve(value, kind, generated=id(node) in generated_reads)
                        elif not reviewed:
                            unknown.append(
                                {"code": resource_code, "line": node.lineno}
                            )
                    elif not import_call and reader_leaf in (
                        "read_csv",
                        "read_json",
                        "read_parquet",
                        "loadtxt",
                        "read_excel",
                        "load",
                        "load_model",
                    ) and name not in local_calls and reader_name not in (
                        "json.load",
                        "pickle.load",
                        "yaml.load",
                        "yaml.safe_load",
                    ):
                        if node.args and literal_path(node.args[0]) is not None:
                            resolve(literal_path(node.args[0]), "runtime-read")
                        elif (
                            path not in policy["dynamic_resources"]
                            and path not in policy["reviewed_dynamic"]
                        ):
                            unknown.append(
                                {"code": "dynamic-resource", "line": node.lineno}
                            )
                    if leaf in ("read_text", "read_bytes") and isinstance(
                        node.func, ast.Attribute
                    ):
                        value = literal_path(node.func.value)
                        if value is not None:
                            resolve(value, "pathlib-read")
                        elif (
                            path not in policy["reviewed_dynamic"]
                            and path not in policy["dynamic_resources"]
                        ):
                            unknown.append(
                                {
                                    "code": "dynamic-pathlib-resource",
                                    "line": node.lineno,
                                }
                            )
                    if (
                        leaf == "Path"
                        and node.args
                        and isinstance(node.args[0], ast.Constant)
                        and isinstance(node.args[0].value, str)
                    ):
                        val = node.args[0].value
                        if "." in PurePosixPath(val).name:
                            resolve(val, "path-literal", False)
                    if leaf in (
                        "run",
                        "Popen",
                        "call",
                        "check_call",
                        "check_output",
                    ) and name.startswith("subprocess."):
                        if node.args and isinstance(
                            node.args[0], (ast.List, ast.Tuple)
                        ):
                            for a in node.args[0].elts:
                                if (
                                    isinstance(a, ast.Constant)
                                    and isinstance(a.value, str)
                                    and a.value.endswith((".py", ".sh", ".js", ".ps1"))
                                ):
                                    resolve(a.value, "subprocess-script")
                        elif (
                            path not in policy["dynamic_resources"]
                            and path not in policy["reviewed_dynamic"]
                        ):
                            unknown.append(
                                {"code": "dynamic-subprocess", "line": node.lineno}
                            )
    elif suffix in (".js", ".mjs", ".cjs", ".ts", ".tsx", ".jsx"):
        for value in re.findall(
            r"""(?:from\s*|require\(\s*|import\(\s*|import\s*)["']([^"']+)["']""", text
        ):
            if value.startswith("."):
                resolve(value, "js-import", file_relative=True)
            elif value.startswith(("@/", "~/")):
                unknown.append({"code": "unsupported-js-alias"})
            else:
                imports.append(value)
        for value in re.findall(
            r"""(?:readFileSync|readFile)\(\s*["']([^"']+)["']""", text
        ):
            resolve(value, "runtime-read")
        # A literal URL anchored to the current ES module is a static file read.
        # Escaped strings and other URL bases remain unresolved.
        url_reads = r"""(?:readFileSync|readFile)\(\s*new\s+URL\(\s*(["'])([^"'\\\r\n]+)\1\s*,\s*import\.meta\.url\s*\)"""
        for match_url in re.finditer(url_reads, text):
            resolve(match_url.group(2), "js-url-resource", file_relative=True)
        dynamic_text = re.sub(url_reads, 'readFile("literal"', text)
        # A stable CommonJS path binding and literal __dirname join establish a
        # file-relative read. Computed/escaped arguments and shadowed bindings
        # remain dynamic; no JavaScript or package script is evaluated.
        path_bindings = set(re.findall(
            r'''\b(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*require\(\s*["'](?:node:)?path["']\s*\)[ \t]*(?:;|(?=\r?\n|$))''',
            text,
        ))
        def stable_js_binding(binding, assignments):
            token = re.escape(binding)
            writes = re.findall(r"(?<![\w$])" + token + r"(?:\s*\.\s*[\w$]+|\s*\[[^\]\r\n]*\])?\s*(?:=(?!=|>)|[+*/?&|\-]=|\+\+|--)", text)
            parameters = re.search(r"(?:function\b[^()]*|catch\s*)\([^()]*\b" + token + r"\b|\([^()]*\b" + token + r"\b[^()]*\)\s*=>|\b" + token + r"\s*=>", text)
            destructured = re.search(r"\b(?:const|let|var)\s*[\[{][^;\r\n=]*\b" + token + r"\b|[\[{][^;\r\n=]*\b" + token + r"\b[^;\r\n=]*[\]}]\s*=", text)
            declarations = re.findall(r"\b(?:const|let|var|function|class)\s+" + token + r"\b", text)
            return len(writes) == assignments and len(declarations) == assignments and not parameters and not destructured

        path_bindings = {name for name in path_bindings if stable_js_binding(name, 1)}
        dirname_stable = stable_js_binding("__dirname", 0)
        join_reads = (
            r'''\b(?:readFileSync|readFile)\(\s*([A-Za-z_$][\w$]*)\.join\(\s*__dirname'''
            r'''((?:\s*,\s*(?:"[^"\\\r\n]*"|'[^'\\\r\n]*'))+)\s*\)(?=\s*[,)])'''
        )

        def joined_read(match):
            if match.group(1) not in path_bindings or not dirname_stable:
                return match.group(0)
            parts = re.findall(r'''["']([^"']*)["']''', match.group(2))
            if any(not part or part.startswith(("/", "~")) or ":" in part for part in parts):
                return match.group(0)
            resolve("/".join(parts), "js-dirname-resource", file_relative=True)
            return 'readFile("literal"'

        dynamic_text = re.sub(join_reads, joined_read, dynamic_text)
        if (
            re.search(r"""(?:import|require|readFileSync|readFile)\(\s*[^\s"']""", dynamic_text)
            and path not in policy["dynamic_resources"]
            and path not in policy["reviewed_dynamic"]
        ):
            unknown.append({"code": "dynamic-js-resource"})
    if suffix in (".md", ".rst", ".html", ".css"):
        document = text
        if suffix == ".md":
            # Fenced examples render as literal code, not links or HTML assets.
            # This filter affects dependency extraction only; all bytes are scanned
            # for sensitive content and preserved in the source release.
            lines = []
            fence = None
            for line in text.splitlines(keepends=True):
                if fence:
                    if re.fullmatch(
                        r" {0,3}" + re.escape(fence[0]) + "{" + str(len(fence)) + r",}[ \t]*(?:\r?\n)?",
                        line,
                    ):
                        fence = None
                    continue
                opening = re.match(r" {0,3}(`{3,}|~{3,})([^\r\n]*)", line)
                if opening and not (opening[1][0] == "`" and "`" in opening[2]):
                    fence = opening[1]
                else:
                    lines.append(line)
            document = "".join(lines)
        for value in re.findall(
            r"""(?:\]\(|(?:src|href)=["']|url\(["']?)([^\s\)"'>]+)""", document
        ):
            if not re.match(r"^[a-zA-Z]+:", value):
                resolve(value, "document-resource")
    for value in policy["dynamic_resources"].get(path, []):
        resolve(value, "explicit-dynamic-resource")
    edges.sort(key=lambda x: (x["target"], x["kind"]))
    imports[:] = sorted(set(imports))
    return edges, unknown, imports


def analyze(source, policy=None, *, operation=None):
    policy = load_policy(value=policy)
    root = Path(source).resolve()
    if not root.is_dir():
        raise ReleaseError("Source directory does not exist")
    scan = {}
    files, ignored, errors = inventory(root, policy["max_file_bytes"], audit=scan, operation=operation, byte_limit=policy["max_scan_bytes"])
    budget = EvidenceBudget(MAX_ANALYSIS_EVIDENCE)
    rows, graph, warnings, kinds, licenses, generated = [], {}, [], [], [], {}
    blockers = budget.items()
    analysis_complete = True
    analysis_stop_reason = None
    local_function_cache = {}

    def local_functions(path):
        if path not in local_function_cache:
            names = set()
            data = files[path].content()
            if len(data) <= 1024 * 1024:
                try:
                    tree = ast.parse(data)
                    definitions = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
                    counts = {}
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
                            counts[node.id] = counts.get(node.id, 0) + 1
                        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                            counts[node.name] = counts.get(node.name, 0) + 1
                        elif isinstance(node, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
                            counts[node.name] = counts.get(node.name, 0) + 1
                        elif isinstance(node, ast.MatchMapping):
                            counts[node.rest] = counts.get(node.rest, 0) + 1
                        elif isinstance(node, (ast.Import, ast.ImportFrom)):
                            for item in node.names:
                                key = item.asname or item.name.split('.')[0]
                                counts[key] = counts.get(key, 0) + 1
                    if len(definitions) <= 1000:
                        names = {n.name for n in definitions if counts.get(n.name) == 1 and not n.decorator_list}
                except (SyntaxError, ValueError, RecursionError):
                    pass
            local_function_cache[path] = names
        return local_function_cache[path]

    def classify():
        paths = set(files)
        agent_contexts = playwright_context(files)
        if any(PurePosixPath(p).suffix.lower() in (".py", ".pyw") for p in paths):
            kinds.append("python")
        if any(PurePosixPath(p).suffix == ".ipynb" for p in paths):
            kinds.append("notebook")
        if any(PurePosixPath(p).name == "package.json" for p in paths):
            kinds.append("node")
        if not kinds:
            blockers.append({"code": "unsupported-project"})
        licenses[:] = sorted(
            p
            for p in paths
            if PurePosixPath(p).name.upper().startswith(("LICENSE", "COPYING"))
        )
        if not licenses:
            blockers.append({"code": "missing-license"})
        known_license = False
        for p in licenses:
            t = files[p].content().decode("utf8", errors="replace")
            if (
                "Permission is hereby granted" in t
                or "Apache License" in t
                or "Redistribution and use in source and binary forms" in t
            ):
                known_license = True
        if licenses and not known_license:
            blockers.append({"code": "license-needs-review"})
        for index, path in enumerate(sorted(files)):
            item = files[path]
            data, executable = item.content(), item.executable
            signal(operation, "Analyzing", current=path, files=index, total_files=len(files), bytes_read=scan["bytes_retained"])
            name = PurePosixPath(path).name
            suf = PurePosixPath(path).suffix
            state = "INCLUDE"
            reason = "conservative-source-maintenance"
            transformed = data
            category, evidence_reason = context_rule(path, files, agent_contexts)
            decision = policy["decisions"].get(path)
            if (
                any(
                    p.lower() in ("vendor", "third_party", "third-party")
                    for p in PurePosixPath(path).parts
                )
                and path not in policy["third_party"]
            ):
                state = "UNRESOLVED"
                reason = "third-party-provenance"
            elif name.startswith(".env") and name not in (".env.example", ".env.template"):
                state = "EXCLUDE"
                reason = "private-environment"
            elif category == "private":
                state, reason = "EXCLUDE", evidence_reason
            elif decision and decision["sha256"] != item.sha256:
                state, reason = "UNRESOLVED", "review-decision-stale"
            elif decision:
                state = {"include": "INCLUDE", "exclude": "EXCLUDE", "review": "UNRESOLVED"}[decision["action"]]
                reason = "user-review-required" if state == "UNRESOLVED" else "reviewed-" + decision["action"]
            elif match(path, policy["exclude"]):
                state = "EXCLUDE"
                reason = "explicit-exclude"
            elif path in policy["external"]:
                state = "EXTERNAL"
                reason = "explicit-external"
            elif match(path, policy["include"]) or path in policy["resources"]:
                reason = "explicit-include"
            elif category == "shared":
                reason = evidence_reason
            elif category == "review":
                state, reason = "UNRESOLVED", evidence_reason
            elif suf in TRANSIENT or name in (".DS_Store", "Thumbs.db"):
                state = "EXCLUDE"
                reason = "transient-artifact"
            elif path.startswith(".github/workflows/") and suf in (".yml", ".yaml"):
                state = "INCLUDE" if policy["mode"] != "runtime" else "EXCLUDE"
                reason = "source-maintenance-workflow" if state == "INCLUDE" else "runtime-profile"
            elif name in MAINTENANCE or path.casefold() in (".github/funding.yml", ".github/funding.yaml"):
                state = "INCLUDE" if policy["mode"] != "runtime" else "EXCLUDE"
                reason = "source-maintenance-config" if state == "INCLUDE" else "runtime-profile"
            elif suf not in SOURCE | DOC and name not in META and path not in licenses:
                state = "UNRESOLVED"
                reason = "unclassified-resource"
            if (
                name.casefold() == ".npmrc"
                and state not in ("EXCLUDE", "EXTERNAL")
                and reason != "third-party-provenance"
            ):
                if not npm_preferences(data):
                    state = "UNRESOLVED"
                    reason = "npm-config-needs-review"
                elif reason == "unclassified-resource":
                    state = "INCLUDE"
                    reason = "literal-npm-preferences"
            if (
                policy["mode"] == "runtime"
                and (path.startswith("tests/") or path.startswith("docs/"))
                and reason == "conservative-source-maintenance"
            ):
                state = "EXCLUDE"
                reason = "runtime-profile"
            if (
                suf == ".ipynb"
                and state == "INCLUDE"
                and policy["notebook_outputs"] == "strip"
            ):
                try:
                    transformed = safe_notebook(data)
                    state = "TRANSFORM"
                    reason = "strip-notebook-outputs"
                except (ValueError, TypeError, ReleaseError):
                    state = "UNRESOLVED"
                    reason = "invalid-notebook"
            if state not in ("EXCLUDE", "EXTERNAL") and not agent_config_safe(path, data):
                state, reason = "UNRESOLVED", "agent-config-needs-review"
            python_source = Path(path).suffix.lower() in (".py", ".pyw")
            raw_findings = item.findings
            public_findings = raw_findings if transformed is data else findings(transformed, python_source=python_source)
            if state not in ("EXCLUDE", "EXTERNAL") and (
                public_findings or findings(path.encode())
            ):
                state = "UNRESOLVED"
                reason = "sensitive-content"
            if (
                state not in ("EXCLUDE", "EXTERNAL")
                and (item.binary if transformed is data else b"\x00" in transformed)
                and path not in policy["resources"]
                and reason not in (
                    "sensitive-content", "third-party-provenance", "npm-config-needs-review", "agent-config-needs-review", "playwright-baseline-input",
                    "reviewed-include", "review-decision-stale", "user-review-required"
                )
            ):
                state = "UNRESOLVED"
                reason = "binary-needs-classification"
            row = {
                "path": path,
                "sha256": item.sha256,
                "output_sha256": item.sha256 if transformed is data else digest(transformed),
                "size": item.size,
                "output_size": item.size if transformed is data else len(transformed),
                "executable": executable,
                "state": state,
                "reason": reason,
                "kind": "file",
                "category": category or ("generated" if reason == "transient-artifact" else "source-or-resource"),
                "decision": decision,
                "findings": budget.items(),
            }
            rows.append(row)
            row["findings"].extend({"rule": r, "line": l} for r, l in raw_findings)
            graph[path] = {
                key: budget.items() for key in ("edges", "unresolved", "imports")
            }
            if item.size > PARSE_BYTES:
                if state not in ("EXCLUDE", "EXTERNAL") and (suf in SOURCE | DOC | {".json", ".toml", ".yaml", ".yml"} or name in META):
                    row["state"], row["reason"] = "UNRESOLVED", "parser-file-limit"
                continue
            edges, unknown, imports = dependencies(
                path, transformed, paths, policy, graph[path], local_functions
            )
            resource_edges(path, transformed, paths, evidence=edges, unresolved=unknown)
            if suf == ".json" and state not in ("EXCLUDE", "EXTERNAL"):
                try:
                    json.loads(data)
                except (ValueError, UnicodeDecodeError):
                    blockers.append({"code": "invalid-json", "path": path})
            if name == "pyproject.toml":
                try:
                    tomllib.loads(data.decode("utf8"))
                except (ValueError, UnicodeDecodeError):
                    blockers.append({"code": "invalid-pyproject", "path": path})
        by_path = {r["path"]: r for r in rows}
        # References promote unclassified resources, never explicit exclusions or safety findings.
        changed = True
        while changed:
            changed = False
            for path, info in graph.items():
                if by_path[path]["state"] not in ("INCLUDE", "TRANSFORM"):
                    continue
                for e in info["edges"]:
                    target = by_path[e["target"]]
                    if (
                        (target["state"] == "UNRESOLVED" or (target["state"] == "EXCLUDE" and target["reason"] == "transient-artifact"))
                        # Dependencies establish necessity, never approval of an
                        # explicit decision or of bytes changed since review.
                        and target.get("decision") is None
                        and (
                            target["reason"] == "transient-artifact"
                            or
                            target["reason"] == "unclassified-resource"
                            or (target["reason"] == "binary-needs-classification" and e["kind"] != "path-literal")
                        )
                    ):
                        target["state"] = "INCLUDE"
                        target["reason"] = "dependency:" + path
                        changed = True
        for row in rows:
            if row["state"] == "UNRESOLVED":
                blockers.append({"code": row["reason"], "path": row["path"]})
            if row["state"] in ("INCLUDE", "TRANSFORM"):
                for u in graph[row["path"]]["unresolved"]:
                    blockers.append({"path": row["path"], **u})
                for e in graph[row["path"]]["edges"]:
                    if by_path[e["target"]]["state"] not in ("INCLUDE", "TRANSFORM"):
                        blockers.append(
                            {
                                "code": "dependency-not-included",
                                "path": row["path"],
                                "target": e["target"],
                            }
                        )
        for lic in licenses:
            if by_path[lic]["state"] not in ("INCLUDE", "TRANSFORM"):
                blockers.append({"code": "license-excluded", "path": lic})
        for reviewed_path in policy["decisions"]:
            if reviewed_path not in paths:
                blockers.append({"code": "review-decision-missing", "path": reviewed_path})
        for resource in policy["resources"]:
            if resource not in paths:
                blockers.append({"code": "explicit-resource-missing", "path": resource})
        if policy["external"]:
            blockers.append({"code": "external-validation-required"})
        if not any(PurePosixPath(p).name.lower().startswith("readme") for p in paths):
            readme = draft_readme(files, policy)
            if readme is None:
                blockers.append({"code": "missing-readme-and-workflow-evidence"})
            elif findings(readme):
                blockers.append({"code": "unsafe-generated-readme"})
            else:
                generated["README.md"] = readme.decode("utf8")
        for group in ("build", "dist", "output", "outputs", "results", "checkpoints"):
            if any(p.startswith(group + "/") for p in paths):
                warnings.append({"code": "generated-or-research-directory", "path": group})

    try:
        blockers.extend(errors)
        if scan["stop_reason"] is not None:
            analysis_complete = False
            analysis_stop_reason = "inventory-incomplete"
        else:
            classify()
    except EvidenceLimit:
        analysis_complete = False
        analysis_stop_reason = "analysis-evidence-limit"
        list.append(blockers, {"code": "analysis-evidence-limit", "analysis_complete": False})
    except (OSError, ReleaseError):
        analysis_complete = False
        analysis_stop_reason = "source-changed-or-unreadable"
        list.append(blockers, {"code": "source-changed-or-unreadable", "analysis_complete": False})
    except RecursionError:
        analysis_complete = False
        analysis_stop_reason = "analysis-depth-limit"
        list.append(blockers, {"code": "analysis-depth-limit", "analysis_complete": False})
    if not analysis_complete:
        # Snapshot every retained payload, including files not reached by analysis.
        # Pending rows cannot be mistaken for approved publication decisions.
        recorded = {row["path"] for row in rows}
        for index, path in enumerate(sorted(files)):
            item = files[path]
            executable = item.executable
            signal(operation, "Analyzing", current=path, files=index, total_files=len(files), bytes_read=scan["bytes_retained"])
            if path not in recorded:
                sha = item.sha256
                rows.append({
                    "path": path, "sha256": sha, "output_sha256": sha,
                    "size": item.size, "output_size": item.size, "executable": executable,
                    "state": "UNRESOLVED", "reason": "analysis-incomplete",
                    "kind": "file", "findings": [],
                })
    analysis = {
        "complete": analysis_complete,
        "stop_reason": analysis_stop_reason,
        "evidence_items_charged": budget.retained,
        "evidence_items_retained": (
            sum(len(row["findings"]) for row in rows)
            + sum(len(items) for info in graph.values() for items in info.values())
            + len(blockers)
            - int(analysis_stop_reason in ("analysis-evidence-limit", "analysis-depth-limit"))
        ),
        "evidence_item_limit": budget.limit,
        "details_omitted_at_least": budget.omitted_at_least,
        "count_scope": "findings, dependency edges/imports/unresolved references and blocker details; charges are not refunded after deduplication or invalid declarations; one terminal diagnostic is reserved separately",
    }
    rows += ignored
    rows.sort(key=lambda x: x["path"])
    snapshot = digest(
        canonical(
            [{k: r[k] for k in ("path", "sha256", "executable", "kind")} for r in rows]
        )
    )
    plan = {
        "schema": 1,
        "policy_version": VERSION,
        "tool_version": __version__,
        "policy": policy,
        "project_types": kinds,
        "snapshot_sha256": snapshot,
        "snapshot_scope": "retained inventory; see scan.complete before treating it as complete",
        "scan": scan,
        "analysis": analysis,
        "blocker_summary": blocker_summary(blockers, scan["complete"] and analysis_complete),
        "files": rows,
        "generated_files": generated,
        "dependencies": graph,
        "licenses": licenses,
        "blockers": blockers,
        "warnings": warnings,
        "status": "BLOCKED"
        if not scan["complete"] or not analysis_complete
        else ("UNSUPPORTED" if not kinds else ("BLOCKED" if blockers else "PLANNED")),
    }
    plan["plan_sha256"] = digest(canonical(plan))
    return plan


def freeze(source, work, policy=None):
    separate(source, work)
    plan = analyze(source, policy)
    work = Path(work)
    if work.exists() and any(work.iterdir()):
        raise ReleaseError("Work directory must be new or empty")
    work.mkdir(parents=True, exist_ok=True)
    atomic_json(work / "plan.json", plan)
    atomic_json(work / "source.json", {"source": str(Path(source).resolve())})
    return plan


def verify_plan(plan):
    body = {k: v for k, v in plan.items() if k != "plan_sha256"}
    if (
        plan.get("schema") != 1
        or plan.get("policy_version") != VERSION
        or plan.get("tool_version") != __version__
        or digest(canonical(body)) != plan.get("plan_sha256")
    ):
        raise ReleaseError("Plan integrity or policy version mismatch")


def plan_diff(before, after):
    a = {r["path"]: r for r in before["files"]}
    b = {r["path"]: r for r in after["files"]}
    return {
        "added": sorted(set(b) - set(a)),
        "removed": sorted(set(a) - set(b)),
        "changed": [p for p in sorted(set(a) & set(b)) if a[p] != b[p]],
        "content_changed": [p for p in sorted(set(a) & set(b)) if a[p].get("sha256") != b[p].get("sha256")],
        "decisions_changed": [p for p in sorted(set(a) & set(b)) if any(a[p].get(k) != b[p].get(k) for k in ("state", "reason", "output_sha256", "decision"))],
        "tool_changed": before.get("tool_version") != after.get("tool_version"),
        "policy_changed": before["policy"] != after["policy"],
    }
