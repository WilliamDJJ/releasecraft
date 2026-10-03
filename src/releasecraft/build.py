"""Staged deterministic archives and integrity verification."""

from __future__ import annotations
import json
import hashlib
from pathlib import Path
import shutil
import tempfile
import zipfile
from .analyze import analyze, verify_plan
from .residue import private_state, agent_config_safe
from .operation import signal
from .streaming import ContentScanner, PARSE_BYTES, SpaceError, chunks, copy_safe, hash_file, require_space
from .archive import frozen_archive, open_archive, member_index, manifest_from
from .safety import (
    ReleaseError,
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
    selected_bytes = sum(r.get("output_size", r["size"]) for r in plan["files"] if r["state"] in ("INCLUDE", "TRANSFORM"))
    require_space(output.parent, selected_bytes * 2 + len(canonical(plan)) * 4 + 65536)
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
            executable = row["executable"]
            dest = repo / rel
            mkdir(dest.parent)
            if row["state"] == "TRANSFORM":
                data, actual_executable = read_safe(source, rel, PARSE_BYTES)
                if digest(data) != row["sha256"] or actual_executable != executable:
                    raise ReleaseError("Source changed while staging")
                data = safe_notebook(data)
                if digest(data) != row["output_sha256"] or findings(data):
                    raise ReleaseError("Staging content failed integrity or safety check")
                write(dest, data)
                size = len(data)
            else:
                stream = owned_tree.open_new(dest.relative_to(owned_tree.path).as_posix()) if owned_tree else dest.open("xb")
                with stream as target:
                    _, size, actual_executable = copy_safe(source, rel, target, expected=row["sha256"], operation=operation)
                if size != row["size"] or actual_executable != executable:
                    raise ReleaseError("Source changed while staging")
            copied_bytes += size
            mode = 0o755 if executable else 0o644
            dest.chmod(mode)
            entries.append(
                {
                    "path": rel,
                    "sha256": row["output_sha256"],
                    "size": size,
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
                        "after": row["output_sha256"],
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
            "tool_version": plan["tool_version"],
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
            for rel in sorted(archive_modes):
                signal(operation, "Writing archive", current=rel, total_files=len(entries) + 1)
                path = repo / rel
                info = zipfile.ZipInfo(rel, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                mode = archive_modes[rel]
                info.external_attr = (0o100000 | mode) << 16
                info.compress_type = zipfile.ZIP_STORED
                info.file_size = path.stat().st_size
                with z.open(info, "w", force_zip64=info.file_size >= zipfile.ZIP64_LIMIT) as member:
                    copy_safe(repo, rel, member, operation=operation)
        sha = hash_file(archive, operation)
        write(staging / "release.zip.sha256", (sha + "  release.zip\n").encode("ascii"))
        signal(operation, "Verifying archive", archive_bytes=archive.stat().st_size)
        report = verify_archive(archive, operation=operation)
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



def _verify_frozen(frozen, operation=None):
    errors = []
    with open_archive(frozen) as archive:
        members = member_index(archive)
        manifest = manifest_from(archive, members)
        rows = {r["path"]: r for r in manifest["files"]}
        for rel, info in members.items():
            scanner = ContentScanner(info.file_size, Path(rel).suffix.lower() in (".py", ".pyw"))
            h = hashlib.sha256()
            with archive.open(info) as stream:
                for block in chunks(stream, info.file_size, operation, "Verifying archive", rel):
                    h.update(block)
                    scanner.feed(block)
            f = scanner.finish() + findings(rel.encode())
            if rel != MANIFEST:
                row = rows[rel]
                if h.hexdigest() != row["sha256"] or info.file_size != row["size"] or (info.external_attr >> 16) & 0o777 != row["mode"]:
                    errors.append({"code": "integrity-mismatch", "path_id": digest(rel.encode())[:16]})
            if Path(rel).name.casefold() == ".npmrc" and (not scanner.small or not npm_preferences(bytes(scanner.buffer))):
                errors.append({"code": "npm-config-needs-review", "path_id": digest(rel.encode())[:16]})
            if private_state(rel):
                errors.append({"code": "private-agent-or-auth-state", "path_id": digest(rel.encode())[:16]})
            if not agent_config_safe(rel, bytes(scanner.buffer)):
                errors.append({"code": "agent-config-needs-review", "path_id": digest(rel.encode())[:16]})
            if f:
                errors.append({"code": "sensitive-content", "path_id": digest(rel.encode())[:16], "rules": sorted({r for r, _ in f})})
            if len(errors) >= 1000:
                errors.append({"code": "archive-diagnostic-limit", "complete": False})
                break
        if not any(Path(p).name.upper().startswith(("LICENSE", "COPYING")) for p in rows):
            errors.append({"code": "missing-license"})
    return errors


def verify_archive(archive, *, operation=None):
    sha, errors = None, []
    try:
        with frozen_archive(archive, operation) as frozen:
            sha = frozen.sha256
            errors = _verify_frozen(frozen, operation)
    except SpaceError:
        errors.append({"code": "insufficient-disk-space"})
    except (OSError, ValueError, KeyError, TypeError, RuntimeError, zipfile.BadZipFile, ReleaseError):
        errors.append({"code": "invalid-archive-or-manifest"})
    return {"schema": 1, "status": "FAILED" if errors else "CANDIDATE", "archive_sha256": sha,
            "static_checks": "failed" if errors else "passed", "runtime_checks": "not-run", "errors": errors}


def extract_verified(archive, dest, *, operation=None):
    with frozen_archive(archive, operation) as frozen:
        report = verify_archive(frozen, operation=operation)
        if report["status"] != "CANDIDATE":
            raise ReleaseError("Archive failed static checks")
        dest = Path(dest)
        if dest.exists():
            raise ReleaseError("Extraction destination must not exist")
        with open_archive(frozen) as source:
            members = member_index(source)
            manifest = manifest_from(source, members)
            require_space(dest.parent, sum(i.file_size for i in members.values()))
            dest.parent.mkdir(parents=True, exist_ok=True)
            staging = Path(tempfile.mkdtemp(prefix=".releasecraft-extract-", dir=dest.parent))
            try:
                for rel, info in members.items():
                    path = staging / rel
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with source.open(info) as stream, path.open("xb") as target:
                        for block in chunks(stream, info.file_size, operation, "Extracting", rel):
                            target.write(block)
                    path.chmod((info.external_attr >> 16) & 0o777)
                # Atomic no-overwrite publication uses the same anchored directory core.
                from .directory import Directory
                with Directory(dest.parent) as parent:
                    parent.commit_directory(staging.name, dest.name)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
        return manifest


def verify_cached(archive, plan):
    """Match an existing candidate to selected content and public policy, not only itself."""
    verify_plan(plan)
    with frozen_archive(archive) as frozen:
        report = verify_archive(frozen)
        if report["status"] != "CANDIDATE":
            raise ReleaseError("Invalid cached release")
        with open_archive(frozen) as source:
            manifest = manifest_from(source, member_index(source))
    expected = {r["path"]: (r["output_sha256"], 0o755 if r["executable"] else 0o644)
                for r in plan["files"] if r["state"] in ("INCLUDE", "TRANSFORM")}
    expected.update({name: (digest(text.encode("utf8")), 0o644) for name, text in plan.get("generated_files", {}).items()})
    actual = {r["path"]: (r["sha256"], r["mode"]) for r in manifest["files"]}
    if (actual != expected or manifest.get("commands") != plan["policy"]["commands"]
            or manifest.get("claims") != plan["policy"]["claims"]
            or manifest.get("policy_version") != plan["policy_version"]
            or manifest.get("tool_version") != plan["tool_version"]
            or manifest.get("mode") != plan["policy"]["mode"]):
        raise ReleaseError("Cached release does not match the active plan")
    return report
