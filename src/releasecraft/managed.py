"""Owned project output with private audit, anchored writes and atomic publication."""
from __future__ import annotations
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import re
import stat
import uuid
from itertools import islice
from .storage import Storage, StorageBlocked, AUDIT_BYTES, OWNER_COUNT
from .directory import Directory, identity
from .operation import Operation, Cancelled, signal
from .streaming import SpaceError, require_space
from .safety import ReleaseError, atomic_json, canonical, digest, read_safe, separate

OUTPUT_NAME = "releasecraft-output"
MARKER = ".releasecraft-output.json"


def state_directory():
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData/Local"))
    else:
        base = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return base / "Releasecraft"


def owned_output(path, source, state=None):
    """A marker copied from an input project is insufficient to authorize pruning."""
    try:
        marker = json.loads(read_safe(path, MARKER, 4096)[0])
        token = marker.get("owner", "")
        if set(marker) != {"schema", "owner"} or marker["schema"] != 1 or not re.fullmatch(r"[0-9a-f]{32}", token):
            return False
        record = json.loads(read_safe(Path(state or state_directory()) / "owners", token + ".json", 4096)[0])
        return record == {"schema": 1, "owner": token, "source": identity(Path(source).stat()), "output": identity(Path(path).stat())}
    except (OSError, ReleaseError, ValueError, TypeError, AttributeError):
        return False


@contextmanager
def lease(directory):
    """OS-released lease, so crashes cannot leave a stale exclusive lock."""
    directory.check()
    read_safe(directory.path, ".lease", 1)
    if os.name == "nt":
        from .windows import FileInfo, checked
        k = directory.kernel
        handle = k.CreateFileW(str(directory.path / ".lease"), 0xC0000000, 0, None, 3, 0x00200000, None)
        if handle == ctypes.c_void_p(-1).value:
            raise ReleaseError("Output is busy or inaccessible")
        try:
            info = FileInfo()
            checked(k.GetFileInformationByHandle(handle, ctypes.byref(info)))
            if info.attributes & 0x400 or info.links != 1:
                raise ReleaseError("Unsafe output lease")
            yield
        finally:
            k.CloseHandle(handle)
    else:
        import fcntl
        fd = os.open(".lease", os.O_RDWR | os.O_NOFOLLOW, dir_fd=directory.fd)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
                raise ReleaseError("Unsafe output lease")
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            yield
        finally:
            os.close(fd)


def prepare(source, output=None, policy=None, operation=None, *, review_only=False):
    try:
        return _prepare(source, output, policy, operation, review_only=review_only)
    except SpaceError:
        return {"status": "BLOCKED", "code": "insufficient-disk-space", "problems": [{"code": "insufficient-disk-space"}]}
    except StorageBlocked:
        return {"status": "BLOCKED", "code": "STORAGE_BLOCKED", "problems": [{"code": "private-storage-blocked"}]}


def _prepare(source, output=None, policy=None, operation=None, *, review_only=False):
    """Prepare a source CANDIDATE, never execute selected project code."""
    from .analyze import analyze
    from .build import assemble, verify_archive
    from .diagnostics import plan_summary
    op = operation or Operation()
    state = Path(os.path.abspath(op.state_directory or state_directory()))
    op.state_directory = state
    source = Path(os.path.abspath(source))
    output = Path(os.path.abspath(output or source / OUTPUT_NAME))
    if output.name != OUTPUT_NAME:
        raise ReleaseError("Choose a dedicated releasecraft-output directory")
    if output != source / OUTPUT_NAME:
        separate(source, output)
    separate(source, state)
    separate(output, state)
    op.check()
    with Directory(source) as selected, Directory(output.parent) as parent, Storage(state) as storage:
        storage.maintain()
        storage.capacity(AUDIT_BYTES)
        with Directory(state / "owners", create=True) as owners, Directory(state / "jobs", create=True) as jobs:
            if output.exists():
                if not owned_output(output, source, state):
                    raise ReleaseError("Existing output is not owned by Releasecraft for this project")
            else:
                with os.scandir(owners.path) as listing:
                    if len(list(islice(listing, OWNER_COUNT))) >= OWNER_COUNT:
                        raise StorageBlocked("Output registration limit")
                parent.mkdir(OUTPUT_NAME)
                with Directory(output) as created:
                    owner = uuid.uuid4().hex
                    owners.write_new(owner + ".json", canonical({"schema": 1, "owner": owner, "source": selected.stamp, "output": created.stamp}))
                    created.write_new(MARKER, canonical({"schema": 1, "owner": owner}))
                    created.write_new(".lease", b"0")
            with Directory(output) as destination, lease(destination):
                row, tree = storage.new_job()
                run_id = row['id']
                job = tree.path
                result = {"status":"FAILED", "problems":[]}
                pending = ".pending-" + run_id
                final = "release-" + run_id[:12]
                published = False
                written_files = {}
                pending_stamp = None
                try:
                    signal(op, "Scanning", files=0, bytes_read=0, total_files=None)
                    plan = analyze(source, policy, operation=op)
                    plan_bytes = canonical(plan)
                    if len(plan_bytes) > AUDIT_BYTES // 2:
                        raise StorageBlocked("Private plan evidence exceeds retention limit")
                    tree.write("plan.json", plan_bytes)
                    if review_only or plan["status"] != "PLANNED":
                        result = {"status": plan["status"], "summary": plan_summary(plan), "problems": plan["blockers"], "audit": str(job)}
                        return result
                    storage.reserve_stage(plan, tree)
                    assembled = assemble(source, plan, job / "stage", operation=op, owned_tree=tree)
                    archive_path = job / "stage/release.zip"
                    archive_size = archive_path.stat().st_size
                    signal(op, "Verifying", archive_bytes=archive_size)
                    checked = verify_archive(archive_path, operation=op)
                    if checked["status"] != "CANDIDATE" or checked["archive_sha256"] != assembled["archive_sha256"]:
                        raise ReleaseError("Candidate verification failed")
                    selected.check()
                    destination.check()
                    if not owned_output(output, source, state):
                        raise ReleaseError("Output ownership changed")
                    require_space(output, archive_size + 65536)
                    destination.mkdir(pending)
                    payload = {
                        'release.zip.sha256': (checked['archive_sha256'] + '  release.zip\n').encode('ascii'),
                        'CHECKS.json': canonical({**checked, 'scope': 'Source candidate; target runtime has not been executed'}),
                    }
                    with Directory(output / pending) as staging:
                        pending_stamp = staging.stamp
                        for name, data in payload.items():
                            written_files[name] = staging.write_new(name, data)
                        written_files['release.zip'] = staging.copy_new('release.zip', archive_path, checked['archive_sha256'], op)
                    signal(op, "Publishing", files=len(plan["files"]), archive_bytes=archive_size)
                    if analyze(source, plan["policy"], operation=op)["plan_sha256"] != plan["plan_sha256"]:
                        raise ReleaseError("Source changed before publication")
                    selected.check()
                    op.check()
                    destination.commit_verified(pending, final, pending_stamp, {
                        **{name: (written_files[name], digest(data), len(data)) for name, data in payload.items()},
                        'release.zip': (written_files['release.zip'], checked['archive_sha256'], archive_size),
                    })
                    published = True
                    result = {**checked, "output": str(output / final), "audit": str(job), "summary": plan_summary(plan), "problems": [],
                              "payload_files": sum(row['state'] in ('INCLUDE', 'TRANSFORM') for row in plan['files']) + len(plan.get('generated_files', {})),
                              "archive_bytes": archive_size}
                    return result
                except Cancelled:
                    result = {"status": "CANCELLED", "audit": str(job), "problems": []}
                    return result
                except StorageBlocked:
                    result = {"status":"BLOCKED", "code":"STORAGE_BLOCKED", "audit":str(job), "problems":[{"code":"private-storage-blocked"}]}
                    return result
                except (OSError, ReleaseError, ValueError, TypeError):
                    # A post-rename verification failure is retained for review;
                    # never report it as a successful package or erase unknown data.
                    result = {"status": "FAILED", "code": "operation-rejected", "published": published or (output / final).exists()}
                    raise
                finally:
                    # Never recursively delete an unexpected directory or user content.
                    if not published and (output / pending).exists():
                        try:
                            with Directory(output / pending) as abandoned:
                                if abandoned.stamp != pending_stamp:
                                    raise ReleaseError('Pending directory replaced; retained for review')
                                for name, stamp in written_files.items():
                                    if (abandoned.path / name).exists():
                                        abandoned.remove_verified(name, {'kind':'file', 'identity':stamp, 'sha256': checked['archive_sha256'] if name == 'release.zip' else digest(payload[name]), 'size': archive_size if name == 'release.zip' else len(payload[name])})
                            destination.remove_directory(pending)
                        except (OSError, ReleaseError):
                            try:
                                tree.write("cleanup.json", canonical({"status": "RETAINED", "code": "owned-pending-output-needs-review"}))
                            except (OSError, ReleaseError):
                                pass
                            result["storage_warning"] = "public-pending-retained"
                    try:
                        storage.finish(tree, result)
                    except (OSError, ReleaseError, ValueError, KeyError, TypeError):
                        result["storage_warning"] = "private-maintenance-incomplete"
