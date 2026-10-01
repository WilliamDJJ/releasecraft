"""End-to-end execution of reviewed synthetic fixtures only."""

import json
import shutil
import unittest
import zipfile
import test_core
from releasecraft.build import MANIFEST
from releasecraft.safety import canonical
from releasecraft.validate import validate


class RuntimeTests(unittest.TestCase):
    setUp = test_core.CoreTests.setUp
    tearDown = test_core.CoreTests.tearDown
    put = test_core.CoreTests.put
    output = test_core.CoreTests.output
    runtime_policy = test_core.CoreTests.runtime_policy

    def test_container_bind_root_is_readable_and_flags_are_restricted(self):
        from unittest.mock import patch
        from pathlib import Path

        self.put("main.py", "assert 2 + 2 == 4")
        archive = self.output(self.runtime_policy())

        def inspect(argv, cwd, timeout, env):
            import os

            if os.name != "nt":
                self.assertEqual(Path(cwd).stat().st_mode & 0o777, 0o755)
            else:
                self.assertTrue(os.access(cwd, os.R_OK))
            for flag in (
                "--pull=never",
                "--network=none",
                "--read-only",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--user=65534:65534",
            ):
                self.assertIn(flag, argv)
            self.assertTrue(
                any(str(value).endswith("dst=/input,readonly") for value in argv)
            )
            return {"exit_code": 0, "timeout": False}

        with (
            patch("releasecraft.validate.shutil.which", return_value="docker"),
            patch("releasecraft.validate.run_command", side_effect=inspect),
            patch("releasecraft.validate.subprocess.run"),
        ):
            report = validate(archive, image="python@sha256:" + "a" * 64)
        self.assertEqual(report["status"], "READY")

    def test_container_cleanup_failure_is_reported_as_failure(self):
        from unittest.mock import patch
        import subprocess

        self.put("main.py", "assert True")
        archive = self.output(self.runtime_policy())
        with (
            patch("releasecraft.validate.shutil.which", return_value="docker"),
            patch(
                "releasecraft.validate.run_command",
                return_value={"exit_code": 0, "timeout": False},
            ),
            patch(
                "releasecraft.validate.subprocess.run",
                side_effect=subprocess.TimeoutExpired("docker", 15),
            ),
        ):
            report = validate(archive, image="python@sha256:" + "a" * 64)
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["checks"][0]["error"], "container-cleanup-failed")

    def test_trusted_venv_interpreter_mode_preserves_isolation(self):
        import importlib
        import sys
        from types import SimpleNamespace
        from unittest.mock import patch

        module = importlib.import_module("releasecraft.validate")
        for needs_pip in (False, True):
            policy = self.runtime_policy()
            if needs_pip:
                policy["commands"][0]["argv"] = ["python", "-m", "pip", "--version"]
            archive = self.output(policy, name=f"venv-mode-{needs_pip}")
            for platform, symlinks in (("linux", True), ("darwin", True), ("win32", False)):
                with (
                    self.subTest(platform=platform, needs_pip=needs_pip),
                    patch.object(
                        module, "sys", SimpleNamespace(platform=platform, executable=sys.executable)
                    ),
                    patch.object(module.venv, "EnvBuilder") as builder,
                    patch.object(
                        module, "run_command", return_value={"exit_code": 0, "timeout": False}
                    ),
                ):
                    report = validate(archive, "trusted", trusted=True)
                    builder.assert_called_once_with(
                        with_pip=needs_pip, system_site_packages=False, symlinks=symlinks
                    )
                    builder.return_value.create.assert_called_once()
                    self.assertEqual(report["status"], "READY")
                    self.assertEqual(
                        report["python_environment"], "fresh-venv-no-system-site-packages"
                    )

    def test_node_runtime_and_resource(self):
        if not shutil.which("node"):
            self.skipTest("Node unavailable; Node execution not run")
        self.put("package.json", '{"name":"demo","type":"module","license":"MIT"}')
        self.put(
            "main.js",
            'import fs from "node:fs"; import assert from "node:assert/strict"; const data=JSON.parse(fs.readFileSync("settings.json")); assert.equal(data.answer,42);',
        )
        self.put("settings.json", '{"answer":42}')
        policy = {
            "commands": [{"id": "node", "argv": ["node", "main.js"]}],
            "claims": [
                {"description": "Read JSON and assert the answer", "commands": ["node"]}
            ],
        }
        report = validate(self.output(policy), "trusted", trusted=True)
        self.assertEqual(report["status"], "READY")

    def test_removed_resource_fails_runtime_even_with_rewritten_manifest(self):
        self.put(
            "main.py",
            'import json\nassert json.load(open("settings.json"))["answer"]==42',
        )
        self.put("settings.json", '{"answer":42}')
        archive = self.output(self.runtime_policy())
        bad = self.base / "bad.zip"
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(bad, "w") as dst:
            manifest = json.loads(src.read(MANIFEST))
            manifest["files"] = [
                r for r in manifest["files"] if r["path"] != "settings.json"
            ]
            for info in src.infolist():
                if info.filename == "settings.json":
                    continue
                dst.writestr(
                    info,
                    canonical(manifest)
                    if info.filename == MANIFEST
                    else src.read(info),
                )
        report = validate(bad, "trusted", trusted=True)
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(report["static_checks"], "passed")

    def test_excessive_output_fails(self):
        self.put("main.py", 'import sys\nsys.stdout.write("x"*2000000)')
        report = validate(self.output(self.runtime_policy()), "trusted", trusted=True)
        self.assertEqual(report["status"], "FAILED")
        self.assertTrue(report["checks"][0]["output_limit_exceeded"])

    def test_host_installed_packages_not_borrowed(self):
        self.put("main.py", "import releasecraft\n")
        report = validate(self.output(self.runtime_policy()), "trusted", trusted=True)
        self.assertEqual(report["status"], "FAILED")
        self.assertEqual(
            report["python_environment"], "fresh-venv-no-system-site-packages"
        )

    def test_hostile_target_stays_unexecuted_without_sandbox(self):
        from unittest.mock import patch

        self.put("main.py", 'raise RuntimeError("must never execute")')
        archive = self.output(self.runtime_policy())
        with (
            patch("releasecraft.validate.shutil.which", return_value=None),
            patch("releasecraft.validate.run_command") as execute,
        ):
            report = validate(archive)
        self.assertEqual(report["status"], "BLOCKED")
        self.assertEqual(report["checks"], [])
        execute.assert_not_called()

    def test_explicit_wheelhouse_hashes_recorded(self):
        from releasecraft.safety import digest

        wheels = self.base / "wheels"
        wheels.mkdir()
        (wheels / "fixture.whl").write_bytes(b"not-installed-in-this-test")
        report = validate(
            self.output(self.runtime_policy()),
            "trusted",
            trusted=True,
            wheelhouse=wheels,
        )
        self.assertEqual(report["status"], "READY")
        self.assertEqual(
            report["declared_dependency_wheels"][0]["sha256"],
            digest(b"not-installed-in-this-test"),
        )
