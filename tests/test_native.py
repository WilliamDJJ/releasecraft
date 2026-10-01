import unittest
import test_core


class NativeTests(unittest.TestCase):
    setUp = test_core.CoreTests.setUp
    tearDown = test_core.CoreTests.tearDown
    put = test_core.CoreTests.put
    plan = test_core.CoreTests.plan
    states = test_core.CoreTests.states

    def test_setuptools_package_data(self):
        self.put("src/pkg/__init__.py", "")
        self.put("src/pkg/table.dat", "1 2 3")
        self.put("pyproject.toml", '[tool.setuptools.package-data]\npkg=["*.dat"]\n')
        p = self.plan()
        self.assertEqual(self.states(p)["src/pkg/table.dat"], "INCLUDE")

    def test_manifest_resources(self):
        self.put("assets/table.dat", "1 2")
        self.put("MANIFEST.in", "recursive-include assets *.dat\n")
        self.assertEqual(self.states(self.plan())["assets/table.dat"], "INCLUDE")

    def test_node_files_resources(self):
        self.put("package.json", '{"files":["assets/*.dat"]}')
        self.put("assets/table.dat", "1 2")
        self.assertEqual(self.states(self.plan())["assets/table.dat"], "INCLUDE")

    def test_readme_generated_from_evidence(self):
        (self.source / "README.md").unlink()
        p = self.plan(**test_core.CoreTests.runtime_policy(self))
        self.assertEqual(p["status"], "PLANNED")
        self.assertIn("python main.py", p["generated_files"]["README.md"])

    def test_license_cannot_be_excluded(self):
        self.assertEqual(self.plan(exclude=["LICENSE"])["status"], "BLOCKED")

    def test_pathlib_missing_read_blocks(self):
        self.put("main.py", 'from pathlib import Path\nPath("missing.dat").read_text()')
        self.assertEqual(self.plan()["status"], "BLOCKED")

    def test_pathlib_file_relative_resource(self):
        self.put(
            "main.py",
            'from pathlib import Path\n(Path(__file__).parent / "needed.dat").read_bytes()',
        )
        self.put("needed.dat", "data")
        self.assertEqual(self.plan()["status"], "PLANNED")

    def test_pathlib_absolute_read_blocks(self):
        self.put(
            "main.py",
            'from pathlib import Path\nPath("/opt/private/data.dat").read_bytes()',
        )
        self.assertEqual(self.plan()["status"], "BLOCKED")

    def test_short_json_password_blocks(self):
        self.put("settings.json", '{"password":"1234"}')
        self.assertEqual(self.plan(resources=["settings.json"])["status"], "BLOCKED")

    def test_unquoted_environment_secret_blocks(self):
        self.put(".env.example", "DB_" + "PASSWORD=abc123\n")
        self.assertEqual(self.plan(include=[".env.example"])["status"], "BLOCKED")

    def test_explicit_scientific_log_can_be_retained(self):
        self.put("results/training.log", "epoch 1: loss 0.5\n")
        p = self.plan(resources=["results/training.log"])
        self.assertEqual(self.states(p)["results/training.log"], "INCLUDE")

    def test_notebook_semantic_metadata_is_preserved(self):
        import json
        from releasecraft.safety import safe_notebook

        nb = {
            "nbformat": 4,
            "metadata": {"kernelspec": {"name": "python3"}},
            "cells": [
                {
                    "cell_type": "markdown",
                    "source": ["figure"],
                    "metadata": {"tags": ["parameters"]},
                    "attachments": {"figure.png": {"image/png": "YWJj"}},
                }
            ],
        }
        self.assertEqual(json.loads(safe_notebook(json.dumps(nb).encode())), nb)
