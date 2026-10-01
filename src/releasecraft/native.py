"""Read native packaging declarations without importing build backends."""

import fnmatch
import json
from pathlib import PurePosixPath
import posixpath
import shlex
import tomllib


def package_bases(package, config, paths, parent):
    """Resolve literal setuptools package locations without importing a backend."""
    mapping = config.get("package-dir", {})
    if not isinstance(mapping, dict):
        raise ValueError("Invalid package directory mapping")
    matches = [key for key in mapping if key == "" or package == key or package.startswith(key + ".")]
    if matches:
        key = max(matches, key=len)
        tail = package[len(key):].lstrip(".").replace(".", "/")
        return [str(PurePosixPath(mapping[key]) / tail)]
    packages = config.get("packages", {})
    where = packages.get("find", {}).get("where", [".", "src"]) if isinstance(packages, dict) else [".", "src"]
    if not isinstance(where, list) or not all(isinstance(p, str) for p in where):
        raise ValueError("Invalid package search roots")
    candidates = [str(PurePosixPath(root) / package.replace(".", "/")) for root in where]
    return [base for base in candidates if any(p.startswith(str(parent / base).removeprefix("./") + "/") for p in paths)]


def pattern_matches(candidate, pattern):
    """Packaging globs use path components; '*' never spans directories or dotfiles."""
    parts, patterns = candidate.split("/"), pattern.split("/")
    states = {0}
    for component in patterns:
        if component == "**":
            expanded = set(states)
            for index in sorted(states):
                while index < len(parts) and not parts[index].startswith("."):
                    index += 1
                    expanded.add(index)
            states = expanded
        else:
            states = {i + 1 for i in states if i < len(parts) and (not parts[i].startswith(".") or component.startswith(".")) and fnmatch.fnmatchcase(parts[i], component)}
    return len(parts) in states


def resource_edges(path, data, paths, evidence=None, unresolved=None):
    edges = evidence if evidence is not None else []
    unknown = unresolved if unresolved is not None else []
    start = len(edges)
    unknown_start = len(unknown)
    parent = PurePosixPath(path).parent

    def add(pattern, base="", required=False):
        if not isinstance(pattern, str) or not isinstance(base, str):
            raise ValueError("Invalid resource pattern")
        pattern = posixpath.normpath(str(parent / base / pattern))
        found = False
        for candidate in sorted(paths):
            if pattern_matches(candidate, pattern) or candidate.startswith(
                pattern.rstrip("/") + "/"
            ):
                edges.append({"target": candidate, "kind": "native-package-resource"})
                found = True
        if required and not found:
            unknown.append(
                {"code": "missing-resource", "reference": pattern,
                 "evidence": "native-package-resource"}
            )

    name = PurePosixPath(path).name
    try:
        if name == "pyproject.toml":
            obj = tomllib.loads(data.decode("utf8"))
            project = obj.get("project", {})
            for field in ("readme", "license"):
                value = project.get(field)
                if field == "readme" and isinstance(value, str):
                    add(value, required=True)
                elif isinstance(value, dict) and isinstance(value.get("file"), str):
                    add(value["file"], required=True)
            config = obj.get("tool", {}).get("setuptools", {})
            for pattern in project.get("license-files", config.get("license-files", [])):
                add(pattern, required=True)
            for patterns in config.get("data-files", {}).values():
                if not isinstance(patterns, list):
                    raise ValueError("Invalid data files")
                for pattern in patterns:
                    add(pattern, required=not any(c in pattern for c in "*?["))
            package_data = config.get("package-data", {})
            for package, patterns in package_data.items():
                if not isinstance(patterns, list):
                    raise ValueError("Invalid package data")
                if package == "*":
                    bases = {str(PurePosixPath(p).parent.relative_to(parent)) for p in paths if PurePosixPath(p).name == "__init__.py" and PurePosixPath(p).is_relative_to(parent)}
                else:
                    bases = package_bases(package, config, paths, parent)
                for pattern in patterns:
                    for base in sorted(bases):
                        add(pattern, base)
        elif name == "MANIFEST.in":
            for line in data.decode("utf8").splitlines():
                words = shlex.split(line, comments=True)
                if not words:
                    continue
                if words[0] == "include":
                    for pattern in words[1:]:
                        add(pattern)
                elif words[0] == "recursive-include" and len(words) >= 3:
                    for pattern in words[2:]:
                        add(words[1] + "/**/" + pattern)
                elif words[0] == "graft" and len(words) == 2:
                    add(words[1])
        elif name == "package.json":
            obj = json.loads(data)
            for pattern in obj.get("files", []):
                add(pattern)
            for key in ("main", "module", "types", "typings"):
                if isinstance(obj.get(key), str):
                    add(obj[key], required=True)
            for pattern in (
                obj.get("bin", {}).values()
                if isinstance(obj.get("bin"), dict)
                else [obj.get("bin")]
            ):
                if isinstance(pattern, str):
                    add(pattern, required=True)
    except (ValueError, TypeError, AttributeError):
        del edges[start:]
        del unknown[unknown_start:]
        unknown.append({"code": "invalid-native-manifest"})
    return edges
