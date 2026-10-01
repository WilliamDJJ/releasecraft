"""Runtime validation is opt-in and isolated by default."""

from __future__ import annotations
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import uuid
import venv
from .build import archive_bytes, extract_verified, verify_archive
from .safety import ReleaseError, read_safe, digest


def run_command(argv, cwd, timeout, env):
    import hashlib
    import threading

    p = subprocess.Popen(
        argv,
        cwd=cwd,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=os.name != "nt",
        shell=False,
        creationflags=0x4 if os.name == "nt" else 0,
    )
    job = None
    if os.name == "nt":
        from .windows import ProcessJob

        job = ProcessJob(p)
    h = hashlib.sha256()
    count = 0
    exceeded = False

    def stop():
        try:
            if os.name != "nt":
                os.killpg(p.pid, signal.SIGKILL)
            else:
                job.terminate()
        except ProcessLookupError:
            pass

    def drain():
        nonlocal count, exceeded
        while True:
            chunk = p.stdout.read(65536)
            if not chunk:
                break
            count += len(chunk)
            h.update(chunk)
            if count > 1024 * 1024:
                exceeded = True
                stop()
                break

    reader = threading.Thread(target=drain, daemon=True)
    reader.start()
    timed_out = False
    try:
        p.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        stop()
        p.wait(timeout=10)
    finally:
        stop()
        reader.join(timeout=5)
        if not reader.is_alive():
            p.stdout.close()
        if job:
            job.close()
    return {
        "exit_code": p.returncode,
        "timeout": timed_out,
        "output_sha256_prefix": h.hexdigest(),
        "output_limit_exceeded": exceeded,
        "output_capture_limit": 1048576,
    }


def validate(archive, backend="docker", image=None, trusted=False, wheelhouse=None):
    archive = archive_bytes(archive)
    report = verify_archive(archive)
    if report["status"] == "FAILED":
        return report
    report.update(
        {
            "platform": platform.system(),
            "python": platform.python_version(),
            "backend": backend,
            "checks": [],
        }
    )
    if backend not in ("docker", "trusted"):
        raise ReleaseError("Unknown validation backend")
    if backend == "trusted" and not trusted:
        raise ReleaseError("Host execution requires explicit trust acknowledgement")
    if backend == "docker" and (
        not shutil.which("docker")
        or not image
        or not re.fullmatch(r"[a-zA-Z0-9._/:-]+@sha256:[a-f0-9]{64}", image)
    ):
        report.update(
            status="BLOCKED",
            runtime_checks="not-run",
            errors=[
                {
                    "code": "isolated-runtime-unavailable",
                    "detail": "Docker and an already-installed digest-pinned image are required",
                }
            ],
        )
        return report
    with tempfile.TemporaryDirectory(prefix="releasecraft-verify-") as temp:
        root = Path(temp) / "extracted"
        manifest = extract_verified(archive, root)
        if backend == "docker":
            # The bind-mounted root must be traversable by the unprivileged container UID.
            # Its host parent remains a private TemporaryDirectory.
            root.chmod(0o755)
        from .policy import load_policy

        checked = load_policy(
            value={
                "commands": manifest.get("commands", []),
                "claims": manifest.get("claims", []),
            }
        )
        commands = checked["commands"]
        claims = checked["claims"]
        if not commands or not claims:
            report.update(
                status="BLOCKED",
                runtime_checks="not-run",
                errors=[{"code": "missing-command-claim-coverage"}],
            )
            return report
        env = {
            k: v
            for k, v in os.environ.items()
            if k in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC")
        }
        env.update(
            HOME=str(Path(temp) / "home"),
            USERPROFILE=str(Path(temp) / "home"),
            TMPDIR=str(Path(temp) / "tmp"),
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PIP_CONFIG_FILE=os.devnull,
            PIP_DISABLE_PIP_VERSION_CHECK="1",
        )
        Path(env["HOME"]).mkdir()
        Path(env["TMPDIR"]).mkdir()
        python_executable = sys.executable
        if backend == "trusted":
            environment = Path(temp) / "venv"
            needs_pip = any("pip" in c["argv"] for c in commands)
            venv.EnvBuilder(
                with_pip=needs_pip,
                system_site_packages=False,
                symlinks=sys.platform != "win32",
            ).create(environment)
            binary_dir = environment / ("Scripts" if os.name == "nt" else "bin")
            python_executable = str(
                binary_dir / ("python.exe" if os.name == "nt" else "python")
            )
            env["PATH"] = str(binary_dir) + os.pathsep + env.get("PATH", "")
            report["python_environment"] = "fresh-venv-no-system-site-packages"
        wheels = None
        if wheelhouse:
            origin = Path(wheelhouse).resolve()
            wheels = Path(temp) / "wheels"
            wheels.mkdir()
            report["declared_dependency_wheels"] = []
            total = 0
            candidates = sorted(origin.iterdir())
            if not candidates or len(candidates) > 50:
                raise ReleaseError("Invalid wheelhouse")
            for item in candidates:
                if item.suffix != ".whl":
                    raise ReleaseError("Wheelhouse may contain only wheels")
                data, _ = read_safe(origin, item.name, 128 * 1024 * 1024)
                total += len(data)
                if total > 256 * 1024 * 1024:
                    raise ReleaseError("Wheelhouse exceeds limit")
                (wheels / item.name).write_bytes(data)
                report["declared_dependency_wheels"].append(
                    {"filename": item.name, "sha256": digest(data)}
                )
            env["PIP_NO_INDEX"] = "1"
            env["PIP_FIND_LINKS"] = wheels.as_uri()
        for command in commands:
            argv = command["argv"]
            timeout = command.get("timeout", 60)
            if backend == "trusted":
                if argv[0] == "python":
                    argv = [python_executable, *argv[1:]]
                try:
                    result = run_command(argv, root, timeout, env)
                except OSError:
                    result = {
                        "exit_code": None,
                        "timeout": False,
                        "error": "command-unavailable",
                    }
            else:
                name = "releasecraft-" + uuid.uuid4().hex
                argv = [
                    "docker",
                    "run",
                    "--pull=never",
                    "--rm",
                    "--name",
                    name,
                    "--network=none",
                    "--read-only",
                    "--cap-drop=ALL",
                    "--security-opt=no-new-privileges",
                    "--pids-limit=128",
                    "--memory=512m",
                    "--cpus=1",
                    "--user=65534:65534",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,size=128m",
                    "--mount",
                    f"type=bind,src={root},dst=/input,readonly",
                    "--workdir=/tmp",
                    image,
                    "/bin/sh",
                    "-c",
                    'cp -R /input /tmp/project && cd /tmp/project && exec "$@"',
                    "releasecraft",
                    *argv,
                ]
                if wheels:
                    image_index = argv.index(image)
                    argv[image_index:image_index] = [
                        "--mount",
                        f"type=bind,src={wheels},dst=/wheels,readonly",
                        "--env",
                        "PIP_NO_INDEX=1",
                        "--env",
                        "PIP_FIND_LINKS=file:///wheels",
                    ]
                try:
                    result = run_command(argv, root, timeout, env)
                except OSError:
                    result = {
                        "exit_code": None,
                        "timeout": False,
                        "error": "container-unavailable",
                    }
                finally:
                    try:
                        subprocess.run(
                            ["docker", "rm", "-f", name],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=15,
                            env=env,
                        )
                    except (OSError, subprocess.TimeoutExpired):
                        result = {
                            "exit_code": None,
                            "timeout": False,
                            "error": "container-cleanup-failed",
                        }
            report["checks"].append({"id": command["id"], **result})
            if (
                result.get("exit_code") != 0
                or result.get("timeout")
                or result.get("output_limit_exceeded")
            ):
                break
    passed = len(report["checks"]) == len(commands) and all(
        x.get("exit_code") == 0
        and not x.get("timeout")
        and not x.get("output_limit_exceeded")
        for x in report["checks"]
    )
    report.update(
        status="READY" if passed else "FAILED",
        runtime_checks="passed" if passed else "failed",
        isolation="container-no-network"
        if backend == "docker"
        else "NONE: explicitly trusted source; not safe for untrusted code",
    )
    return report
