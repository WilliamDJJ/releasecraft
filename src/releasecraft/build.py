"""Staged deterministic archives and integrity verification."""

from __future__ import annotations
import json
import io
from pathlib import Path
import shutil
import tempfile
import zipfile
from .analyze import analyze, verify_plan
from .operation import signal
from .safety import (
    ReleaseError,
    atomic_json,
    canonical,
    digest,
    findings,
    npm_preferences,
    read_safe,
    relative,
    safe_notebook,
    separate,
)

MANIFEST = "RELEASE-MANIFEST.json"


def assemble(source, plan, output, *, operation=None, owned_tree=None):
    source = Path(source).resolve()
    # Journal writes use the checked OwnedTree spelling, including NTFS 8.3 aliases.
    # Resolving only the output would break its exact match and relative paths.
    output = Path(output).absolute() if owned_tree is not None else Path(output).resolve()
    separate(source, output)
    verify_plan(plan)
    if output.exists():
        raise ReleaseError("Output already exists; use a fresh destination")
    signal(operation, "Checking snapshot")
    fresh = analyze(source, plan["policy"], operation=operation)
    if fresh["plan_sha256"] != plan["plan_sha256"]:
        raise ReleaseError(
            "Frozen input or decisions changed; analyze and compare again"
        )
    if plan["status"] != "PLANNED":
        raise ReleaseError("Plan contains unresolved release gates")
    if any(
        x["path"].casefold() == MANIFEST.casefold()
        and x["state"] in ("INCLUDE", "TRANSFORM")
        for x in plan["files"]
    ):
        raise ReleaseError("Reserved manifest filename exists in source")
    output.parent.mkdir(parents=True, exist_ok=True)
    if owned_tree is None:
        staging = Path(tempfile.mkdtemp(prefix=".releasecraft-stage-", dir=output.parent))
    else:
        if output != owned_tree.path / "stage":
            raise ReleaseError("Private stage must match its journal")
        owned_tree.mkdir("stage")
        staging = output

    def mkdir(path):
        if owned_tree is None:
            path.mkdir(parents=True, exist_ok=True)
        else:
            owned_tree.mkdir(path.relative_to(owned_tree.path).as_posix())

    def write(path, data):
        if owned_tree is None:
            path.write_bytes(data)
        else:
            owned_tree.write(path.relative_to(owned_tree.path).as_posix(), data)
    try:
        repo = staging / "source"
        mkdir(repo)
        entries = []
        transforms = []
        selected_count = sum(row["state"] in ("INCLUDE", "TRANSFORM") for row in plan["files"])
        copied_bytes = 0
        for row in plan["files"]:
            if row["state"] not in ("INCLUDE", "TRANSFORM"):
                continue
            signal(operation, "Copying", current=row["path"], files=len(entries), total_files=selected_count, bytes_written=copied_bytes)
            rel = relative(row["path"])
            data, executable = read_safe(source, rel, plan["policy"]["max_file_bytes"])
            if digest(data) != row["sha256"]:
                raise ReleaseError("Source changed while staging")
            if row["state"] == "TRANSFORM":
                data = safe_notebook(data)
            if digest(data) != row["output_sha256"] or findings(data, python_source=Path(rel).suffix.lower() in (".py", ".pyw")):
                raise ReleaseError("Staging content failed integrity or safety check")
            dest = repo / rel
            mkdir(dest.parent)
            write(dest, data)
            copied_bytes += len(data)
            mode = 0o755 if executable else 0o644
            dest.chmod(mode)
            entries.append(
                {
                    "path": rel,
                    "sha256": digest(data),
                    "size": len(data),
                    "mode": mode,
                    "classification": "transformed"
                    if row["state"] == "TRANSFORM"
                    else "source",
                }
            )
            if row["state"] == "TRANSFORM":
                transforms.append(
                    {
                        "path": rel,
                        "operation": "strip-notebook-outputs",
                        "before": row["sha256"],
                        "after": digest(data),
                    }
                )
        for rel, text in sorted(plan.get("generated_files", {}).items()):
            relative(rel)
            data = text.encode("utf8")
            if (repo / rel).exists() or findings(data):
                raise ReleaseError("Unsafe generated file")
            write(repo / rel, data)
            (repo / rel).chmod(0o644)
            entries.append(
                {
                    "path": rel,
                    "sha256": digest(data),
                    "size": len(data),
                    "mode": 0o644,
                    "classification": "generated-documentation",
                }
            )
            transforms.append(
                {
                    "path": rel,
                    "operation": "metadata-and-declared-workflow-readme",
                    "after": digest(data),
                }
            )
        entries.sort(key=lambda x: x["path"])
        manifest = {
            "schema": 1,
            "policy_version": plan["policy_version"],
            "mode": plan["policy"]["mode"],
            "files": entries,
            "claims": plan["policy"]["claims"],
            "commands": plan["policy"]["commands"],
            "transforms": transforms,
            "scope": "source release; runtime validation is a separate gate",
        }
        write(repo / MANIFEST, canonical(manifest))
        if findings((repo / MANIFEST).read_bytes()):
            raise ReleaseError("Public manifest contains sensitive values")
        # Recheck the complete inventory after copying, not just files chosen for publication.
        if analyze(source, plan["policy"], operation=operation)["plan_sha256"] != plan["plan_sha256"]:
            raise ReleaseError("Source changed during staging")
        archive = staging / "release.zip"
        archive_modes = {row["path"]: row["mode"] for row in entries}
        archive_modes[MANIFEST] = 0o644
        stream = owned_tree.open_new("stage/release.zip") if owned_tree else archive.open("w+b")
        with stream as target, zipfile.ZipFile(target, "w", compression=zipfile.ZIP_STORED) as z:
            for path in sorted(p for p in repo.rglob("*") if p.is_file()):
                signal(operation, "Writing archive", current=path.relative_to(repo).as_posix(), total_files=len(entries) + 1)
                rel = path.relative_to(repo).as_posix()
                info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                mode = archive_modes[rel]
                info.external_attr = (0o100000 | mode) << 16
                info.compress_type = zipfile.ZIP_STORED
                z.writestr(info, path.read_bytes())
        sha = digest(archive.read_bytes())
        write(staging / "release.zip.sha256", (sha + "  release.zip\n").encode("ascii"))
        signal(operation, "Verifying archive", archive_bytes=archive.stat().st_size)
        report = verify_archive(archive)
        if report["status"] != "CANDIDATE":
            raise ReleaseError("Final archive verification failed")
        write(staging / "validation.json", canonical(report))
        signal(operation, "Completing staging")
        if owned_tree is None:
            staging.rename(output)
        return report
    finally:
        if owned_tree is None and staging.exists():
            shutil.rmtree(staging)


def archive_bytes(archive):
    if isinstance(archive, bytes):
        if len(archive) > 300 * 1024 * 1024:
            raise ReleaseError("Archive too large")
        return archive
    path = Path(archive)
    if path.stat().st_size > 300 * 1024 * 1024:
        raise ReleaseError("Archive too large")
    with path.open("rb") as stream:
        blob = stream.read(300 * 1024 * 1024 + 1)
    if len(blob) > 300 * 1024 * 1024:
        raise ReleaseError("Archive too large")
    return blob


def archive_contents(archive):
    data = {}
    modes = {}
    folded = set()
    total = 0
    with zipfile.ZipFile(io.BytesIO(archive_bytes(archive))) as z:
        for info in z.infolist():
            rel = relative(info.filename)
            if info.is_dir() or rel.casefold() in folded:
                raise ReleaseError("Duplicate or directory archive entry")
            folded.add(rel.casefold())
            mode = info.external_attr >> 16
            if mode & 0o170000 not in (0, 0o100000):
                raise ReleaseError("Archive link or special entry")
            if info.file_size > 128 * 1024 * 1024:
                raise ReleaseError("Archive member too large")
            total += info.file_size
            if total > 256 * 1024 * 1024 or len(data) > 20000:
                raise ReleaseError("Archive size limit")
            data[rel] = z.read(info)
            modes[rel] = mode & 0o777
    for rel in data:
        parts = rel.casefold().split("/")
        if any("/".join(parts[:i]) in folded for i in range(1, len(parts))):
            raise ReleaseError("File/directory prefix conflict")
    return data, modes


def verify_archive(archive):
    blob = archive_bytes(archive)
    sha = digest(blob)
    errors = []
    try:
        data, modes = archive_contents(blob)
        if MANIFEST not in data:
            raise ReleaseError("Missing release manifest")
        manifest = json.loads(data[MANIFEST])
        if not isinstance(manifest, dict):
            raise ReleaseError("Invalid manifest object")
        entries = manifest.get("files")
        if manifest.get("schema") != 1 or not isinstance(entries, list):
            raise ReleaseError("Invalid release manifest")
        expected = {x["path"] for x in entries}
        if len(expected) != len(entries) or expected != set(data) - {MANIFEST}:
            raise ReleaseError("Manifest file set mismatch")
        for row in entries:
            rel = relative(row["path"])
            if (
                digest(data[rel]) != row["sha256"]
                or len(data[rel]) != row["size"]
                or modes[rel] != row["mode"]
            ):
                errors.append(
                    {"code": "integrity-mismatch", "path_id": digest(rel.encode())[:16]}
                )
        for rel, blob in data.items():
            f = findings(blob, python_source=Path(rel).suffix.lower() in (".py", ".pyw")) + findings(rel.encode())
            if Path(rel).name.casefold() == ".npmrc" and not npm_preferences(blob):
                errors.append(
                    {"code": "npm-config-needs-review", "path_id": digest(rel.encode())[:16]}
                )
            if f:
                errors.append(
                    {
                        "code": "sensitive-content",
                        "path_id": digest(rel.encode())[:16],
                        "rules": sorted({r for r, l in f}),
                    }
                )
        if not any(
            Path(p).name.upper().startswith(("LICENSE", "COPYING")) for p in expected
        ):
            errors.append({"code": "missing-license"})
    except (OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile, ReleaseError):
        errors.append({"code": "invalid-archive-or-manifest"})
    return {
        "schema": 1,
        "status": "FAILED" if errors else "CANDIDATE",
        "archive_sha256": sha,
        "static_checks": "failed" if errors else "passed",
        "runtime_checks": "not-run",
        "errors": errors,
    }


def extract_verified(archive, dest):
    blob = archive_bytes(archive)
    report = verify_archive(blob)
    if report["status"] != "CANDIDATE":
        raise ReleaseError("Archive failed static checks")
    dest = Path(dest)
    if dest.exists():
        raise ReleaseError("Extraction destination must not exist")
    data, modes = archive_contents(blob)
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".releasecraft-extract-", dir=dest.parent))
    try:
        for rel, blob in data.items():
            path = staging / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(blob)
            path.chmod(modes[rel])
        staging.rename(dest)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return json.loads(data[MANIFEST])


def verify_cached(archive, plan):
    """Match an existing candidate to selected content and public policy, not only itself."""
    verify_plan(plan)
    blob = archive_bytes(archive)
    report = verify_archive(blob)
    if report["status"] != "CANDIDATE":
        raise ReleaseError("Invalid cached release")
    data, _ = archive_contents(blob)
    manifest = json.loads(data[MANIFEST])
    expected = {
        r["path"]: (r["output_sha256"], 0o755 if r["executable"] else 0o644)
        for r in plan["files"]
        if r["state"] in ("INCLUDE", "TRANSFORM")
    }
    expected.update(
        {
            name: (digest(text.encode("utf8")), 0o644)
            for name, text in plan.get("generated_files", {}).items()
        }
    )
    actual = {r["path"]: (r["sha256"], r["mode"]) for r in manifest["files"]}
    if (
        actual != expected
        or manifest.get("commands") != plan["policy"]["commands"]
        or manifest.get("claims") != plan["policy"]["claims"]
        or manifest.get("policy_version") != plan["policy_version"]
        or manifest.get("mode") != plan["policy"]["mode"]
    ):
        raise ReleaseError("Cached release does not match the active plan")
    return report
