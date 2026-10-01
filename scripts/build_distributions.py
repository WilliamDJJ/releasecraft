"""Build one source release and offline installers from the same frozen source."""

from __future__ import annotations
import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile

from releasecraft.analyze import freeze
from releasecraft.build import MANIFEST, assemble
from releasecraft.policy import load_policy

EPOCH = 315532800


def sha(data):
    return hashlib.sha256(data).hexdigest()


def archive_files(files, destination, kind):
    """Use fixed metadata and sorted member names on every platform."""
    if kind == "zip":
        with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_STORED) as out:
            for name, (data, mode) in sorted(files.items()):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100000 | mode) << 16
                out.writestr(info, data)
    else:
        with open(destination, "wb") as raw:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=raw, mtime=EPOCH
            ) as compressed:
                with tarfile.open(
                    fileobj=compressed, mode="w", format=tarfile.USTAR_FORMAT
                ) as out:
                    for name, (data, mode) in sorted(files.items()):
                        info = tarfile.TarInfo(name)
                        info.size, info.mode, info.mtime = len(data), mode, EPOCH
                        info.uid = info.gid = 0
                        info.uname = info.gname = ""
                        out.addfile(info, io.BytesIO(data))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    source = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if source == output or source in output.parents or output in source.parents:
        parser.error("Output must be separate from the source tree.")
    output.mkdir(parents=True, exist_ok=False)
    policy = load_policy(source / "releasecraft-policy.json")
    # A delivered source ZIP contains generated evidence from its previous build.
    # Keep that input untouched and explicitly omit it from the next release.
    policy["exclude"] = [*policy["exclude"], MANIFEST]
    plan = freeze(source, output / "work", policy)
    if plan["status"] != "PLANNED":
        raise SystemExit("Source analysis blocked. Inspect the private work plan.")
    report = assemble(source, plan, output / "self-release")
    if report["status"] != "CANDIDATE":
        raise SystemExit("Source assembly failed.")
    clean = output / "self-release/source"
    import tomllib

    version = tomllib.loads((clean / "pyproject.toml").read_text())["project"][
        "version"
    ]
    shutil.copyfile(
        output / "self-release/release.zip",
        output / f"releasecraft-{version}-source.zip",
    )
    with tempfile.TemporaryDirectory(prefix="releasecraft-wheel-") as temp:
        build = Path(temp) / "source"
        shutil.copytree(clean, build)
        env = dict(os.environ, SOURCE_DATE_EPOCH=str(EPOCH), PYTHONHASHSEED="0")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "wheel",
                "--no-deps",
                "--no-build-isolation",
                "--no-cache-dir",
                "--wheel-dir",
                str(output),
                str(build),
            ],
            check=True,
            timeout=180,
            env=env,
        )
    wheels = list(output.glob("releasecraft-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("Expected one built wheel.")
    wheel = wheels[0]
    common = {}
    for path in sorted(clean.rglob("*")):
        rel = path.relative_to(clean).as_posix()
        if path.is_file() and (
            rel in ("README.md", "README.zh-CN.md", "LICENSE", "CHANGELOG.md")
            or rel.startswith(("docs/", "examples/"))
        ):
            common[rel] = (path.read_bytes(), 0o644)
    common["install.py"] = ((clean / "packaging/install.py").read_bytes(), 0o644)
    common["Releasecraft.pyw"] = ((clean / "packaging/Releasecraft.pyw").read_bytes(), 0o644)
    common["wheels/" + wheel.name] = (wheel.read_bytes(), 0o644)
    for platform, kind in [("windows", "zip"), ("linux", "tar.gz")]:
        files = dict(common)
        for path in sorted((clean / "packaging" / platform).iterdir()):
            files[path.name] = (
                path.read_bytes(),
                0o755 if path.suffix == ".sh" else 0o644,
            )
        manifest = {
            "version": version,
            "platform": platform,
            "source_sha256": report["archive_sha256"],
            "files": [
                {"path": n, "sha256": sha(d), "mode": m}
                for n, (d, m) in sorted(files.items())
            ],
        }
        files["DISTRIBUTION.json"] = (
            (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode(),
            0o644,
        )
        files = {"releasecraft/" + n: v for n, v in files.items()}
        archive_files(files, output / f"releasecraft-{version}-{platform}.{kind}", kind)
    artifacts = sorted(p for p in output.iterdir() if p.is_file())
    (output / "SHA256SUMS").write_text(
        "".join(f"{sha(p.read_bytes())}  {p.name}\n" for p in artifacts)
    )
    print("Distribution artifacts built. Run clean-platform acceptance before release.")


if __name__ == "__main__":
    main()
