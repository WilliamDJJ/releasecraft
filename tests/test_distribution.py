"""Distribution contracts and public-document navigation checks."""

import importlib.util
import sys
import contextlib
import io
from pathlib import Path
import re
import tarfile
import tempfile
import unittest
from unittest import mock
from releasecraft.safety import ReleaseError
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def module_from_file(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class DistributionTests(unittest.TestCase):
    def test_acceptance_requires_explicit_trust(self):
        module = module_from_file(
            "check_distribution_trust", ROOT / "scripts/check_distribution.py"
        )
        with (
            mock.patch.object(
                sys,
                "argv",
                ["check_distribution.py", "--archive", "missing-windows.zip"],
            ),
            contextlib.redirect_stderr(io.StringIO()),
        ):
            with self.assertRaises(SystemExit) as error:
                module.main()
        self.assertEqual(error.exception.code, 2)

    def test_acceptance_rejects_external_archive_member(self):
        module = module_from_file(
            "check_distribution_paths", ROOT / "scripts/check_distribution.py"
        )
        with tempfile.TemporaryDirectory() as temp:
            archive = Path(temp) / "bad-windows.zip"
            with zipfile.ZipFile(archive, "w") as target:
                target.writestr("../outside", b"blocked")
            with (
                mock.patch.object(sys, "platform", "win32"),
                mock.patch.object(
                    sys,
                    "argv",
                    [
                        "check_distribution.py",
                        "--archive",
                        str(archive),
                        "--trust-distribution",
                    ],
                ),
            ):
                with self.assertRaises(ReleaseError):
                    module.main()
            self.assertFalse((Path(temp) / "outside").exists())

    def test_versions_match(self):
        import tomllib
        import releasecraft

        version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"][
            "version"
        ]
        self.assertEqual(releasecraft.__version__, version)
        from contextlib import redirect_stdout
        from io import StringIO
        from releasecraft.cli import main

        output = StringIO()
        with redirect_stdout(output), self.assertRaises(SystemExit) as exited:
            main(["--version"])
        self.assertEqual(exited.exception.code, 0)
        self.assertEqual(output.getvalue().strip(), f"releasecraft {version}")
        for name in (
            "README.md",
            "README.zh-CN.md",
            "docs/DOWNLOADS.md",
            "CHANGELOG.md",
            "docs/assets/version.svg",
        ):
            self.assertIn(version, (ROOT / name).read_text(encoding="utf-8"))

    def test_local_document_links_exist(self):
        for path in [*ROOT.glob("*.md"), *(ROOT / "docs").glob("*.md")]:
            text = path.read_text(encoding="utf-8")
            links = re.findall(r'\]\(([^)]+)\)|(?:href|src)="([^"]+)"', text)
            for pair in links:
                link = next(x for x in pair if x).split("#")[0]
                if not link or "://" in link or link.startswith("mailto:"):
                    continue
                with self.subTest(document=path.name, link=link):
                    self.assertTrue((path.parent / link).exists())

    def test_zip_and_tar_repeat_exact_bytes(self):
        module = module_from_file(
            "distribution_builder", ROOT / "scripts/build_distributions.py"
        )
        files = {
            "releasecraft/a.txt": (b"alpha\n", 0o644),
            "releasecraft/run.sh": (b"#!/bin/sh\n", 0o755),
        }
        with tempfile.TemporaryDirectory() as temp:
            for kind in ("zip", "tar.gz"):
                first, second = Path(temp) / ("a." + kind), Path(temp) / ("b." + kind)
                module.archive_files(files, first, kind)
                module.archive_files(dict(reversed(list(files.items()))), second, kind)
                self.assertEqual(first.read_bytes(), second.read_bytes())
                if kind == "zip":
                    with zipfile.ZipFile(first) as archive:
                        self.assertEqual(archive.namelist(), sorted(files))
                        self.assertEqual(
                            archive.getinfo("releasecraft/run.sh").external_attr >> 16
                            & 0o777,
                            0o755,
                        )
                else:
                    with tarfile.open(first) as archive:
                        self.assertEqual(archive.getnames(), sorted(files))
                        self.assertEqual(
                            archive.getmember("releasecraft/run.sh").mode, 0o755
                        )

    def test_installer_rejects_missing_wheel_before_creating_environment(self):
        module = module_from_file("bundle_installer", ROOT / "packaging/install.py")
        with tempfile.TemporaryDirectory() as temp:
            module.__file__ = str(Path(temp) / "install.py")
            with self.assertRaisesRegex(SystemExit, "exactly one"):
                module.main()
            self.assertFalse((Path(temp) / ".venv").exists())

    def test_installer_preserves_existing_environment(self):
        module = module_from_file(
            "bundle_installer_existing", ROOT / "packaging/install.py"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "wheels").mkdir()
            (root / "wheels/releasecraft-test.whl").write_bytes(b"fixture")
            (root / ".venv").mkdir()
            marker = root / ".venv/marker"
            marker.write_text("keep")
            module.__file__ = str(root / "install.py")
            with self.assertRaisesRegex(SystemExit, "already exists"):
                module.main()
            self.assertEqual(marker.read_text(), "keep")

    def test_installer_has_no_network_or_global_install(self):
        module = module_from_file(
            "bundle_installer_offline", ROOT / "packaging/install.py"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "wheels").mkdir()
            (root / "wheels/releasecraft-test.whl").write_bytes(b"fixture")
            module.__file__ = str(root / "install.py")
            with (
                mock.patch.object(module.venv, "EnvBuilder") as builder,
                mock.patch.object(module.subprocess, "run") as run,
            ):
                module.main()
            builder.return_value.create.assert_called_once_with((root / ".venv").resolve())
            argv = run.call_args_list[0].args[0]
            self.assertIn("--no-index", argv)
            self.assertIn("--no-deps", argv)
            self.assertTrue(Path(argv[0]).is_relative_to((root / ".venv").resolve()))

    def test_installer_uses_posix_symlinks_and_windows_copies(self):
        from types import SimpleNamespace

        module = module_from_file(
            "bundle_installer_interpreter_mode", ROOT / "packaging/install.py"
        )
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / "wheels").mkdir()
            (root / "wheels/releasecraft-test.whl").write_bytes(b"fixture")
            module.__file__ = str(root / "install.py")
            for platform, symlinks in (("linux", True), ("darwin", True), ("win32", False)):
                with (
                    self.subTest(platform=platform),
                    mock.patch.object(
                        module, "sys", SimpleNamespace(platform=platform, version_info=sys.version_info)
                    ),
                    mock.patch.object(module.venv, "EnvBuilder") as builder,
                    mock.patch.object(module.subprocess, "run"),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    module.main()
                    builder.assert_called_once_with(with_pip=True, symlinks=symlinks)
                    builder.return_value.create.assert_called_once_with((root / ".venv").resolve())

    def test_launchers_forward_arguments_without_policy_changes(self):
        win = (ROOT / "packaging/windows/releasecraft.cmd").read_text()
        linux = (ROOT / "packaging/linux/releasecraft.sh").read_text()
        self.assertIn("%*", win)
        self.assertIn('"$@"', linux)
        self.assertNotIn("ExecutionPolicy", win)
        self.assertNotIn("sudo", linux)

    def test_release_links_target_official_version(self):
        doc = (ROOT / "docs/DOWNLOADS.md").read_text(encoding="utf-8")
        base = "https://github.com/WilliamDJJ/releasecraft/releases/"
        self.assertIn(base + "tag/v1.1", doc)
        for asset in (
            "releasecraft-1.1.0-windows.zip",
            "releasecraft-1.1.0-linux.tar.gz",
            "releasecraft-1.1.0-source.zip",
            "releasecraft-1.1.0-py3-none-any.whl",
            "SHA256SUMS",
            "VALIDATION.md",
        ):
            self.assertIn(base + "download/v1.1/" + asset, doc)
        for name in ("README.md", "README.zh-CN.md"):
            self.assertIn(base + "tag/v1.1", (ROOT / name).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
