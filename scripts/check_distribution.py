"""Acceptance check for a trusted Releasecraft platform bundle on its target OS."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import tarfile
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument(
        "--trust-distribution",
        action="store_true",
        help="Permit execution of this reviewed distribution",
    )
    args = parser.parse_args()
    if not args.trust_distribution:
        parser.error(
            "Explicit --trust-distribution is required; this is not a sandbox."
        )
    archive = args.archive.resolve()
    windows = sys.platform == "win32"
    if windows != archive.name.endswith("-windows.zip"):
        parser.error("Run the Windows ZIP on Windows or Linux tar.gz on Linux.")
    if not windows and not sys.platform.startswith("linux"):
        parser.error("Only Windows and Linux are acceptance targets.")
    from releasecraft.safety import relative

    with tempfile.TemporaryDirectory(prefix="releasecraft acceptance ") as temp:
        root = Path(temp)
        # Inspect all member names and types before creating any files.
        payload = {}
        total = 0
        if windows:
            with zipfile.ZipFile(archive) as source:
                for info in source.infolist():
                    name = relative(info.filename)
                    if (
                        not name.startswith("releasecraft/")
                        or info.is_dir()
                        or (info.external_attr >> 16) & 0o170000 not in (0, 0o100000)
                    ):
                        raise ValueError("Unexpected archive member")
                    if name in payload or info.file_size > 32 * 1024 * 1024:
                        raise ValueError("Duplicate or oversized member")
                    total += info.file_size
                    if total > 128 * 1024 * 1024 or len(payload) >= 10000:
                        raise ValueError("Distribution too large")
                    payload[name] = source.read(info)
        else:
            with tarfile.open(archive) as source:
                for info in source.getmembers():
                    name = relative(info.name)
                    if not name.startswith("releasecraft/") or not info.isfile():
                        raise ValueError("Unexpected archive member")
                    if name in payload or info.size > 32 * 1024 * 1024:
                        raise ValueError("Duplicate or oversized member")
                    total += info.size
                    if total > 128 * 1024 * 1024 or len(payload) >= 10000:
                        raise ValueError("Distribution too large")
                    payload[name] = source.extractfile(info).read()
        if sum(map(len, payload.values())) > 128 * 1024 * 1024:
            raise ValueError("Distribution too large")
        for name, data in payload.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        bundle = root / "releasecraft"
        manifest = json.loads(
            (bundle / "DISTRIBUTION.json").read_text(encoding="utf-8")
        )
        expected = {row["path"] for row in manifest["files"]}
        if {x.removeprefix("releasecraft/") for x in payload} != expected | {
            "DISTRIBUTION.json"
        }:
            raise ValueError("Manifest file set mismatch")
        for row in manifest["files"]:
            name = relative(row["path"])
            if (
                hashlib.sha256((bundle / name).read_bytes()).hexdigest()
                != row["sha256"]
            ):
                raise ValueError("Distribution integrity mismatch")
        env = {
            k: v
            for k, v in os.environ.items()
            if k.upper()
            in ("PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "TEMP", "TMP", "PATHEXT")
        }
        env.update(
            PYTHONNOUSERSITE="1",
            PYTHONDONTWRITEBYTECODE="1",
            PIP_NO_INDEX="1",
            PIP_CONFIG_FILE=os.devnull,
        )

        def run(argv, expected=0):
            result = subprocess.run(
                [str(x) for x in argv],
                cwd=bundle,
                env=env,
                capture_output=True,
                timeout=120,
            )
            if result.returncode != expected:
                raise RuntimeError("Acceptance command failed: " + str(argv[0]))

        run([sys.executable, bundle / "install.py"])
        python = bundle / (
            ".venv/Scripts/python.exe" if windows else ".venv/bin/python"
        )
        cli = [python, "-m", "releasecraft"]
        run(cli + ["--version"])
        run(
            cli
            + [
                "plan",
                "examples/demo",
                "--config",
                "examples/demo-policy.json",
                "--work",
                root / "work",
            ]
        )
        run(
            cli
            + [
                "build",
                "examples/demo",
                "--plan",
                root / "work/plan.json",
                "--output",
                root / "release",
            ],
            3,
        )
        run(cli + ["verify", root / "release/release.zip"], 3)
        run(
            cli
            + [
                "validate",
                root / "release/release.zip",
                "--backend",
                "trusted",
                "--trust-project",
                "--report",
                root / "validation.json",
            ]
        )
        print(
            json.dumps(
                {
                    "status": "PASSED",
                    "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "platform": sys.platform,
                    "version": manifest["version"],
                }
            )
        )


if __name__ == "__main__":
    main()
