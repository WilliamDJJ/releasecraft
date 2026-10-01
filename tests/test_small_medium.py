"""Independent small/medium project contracts; all payloads are synthetic."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from releasecraft.analyze import analyze
from releasecraft.build import assemble, extract_verified


class SmallMediumTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="releasecraft small medium ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "project"
        self.source.mkdir()
        self.put("LICENSE", "Permission is hereby granted, free of charge, to any person obtaining a copy.\n")
        self.put("README.md", "# Synthetic project\nRun the bundled entry point locally.\n")

    def put(self, path, content):
        target = self.source / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8", newline="\n")

    def planned(self, expected, *, command=None):
        plan = analyze(self.source)
        self.assertEqual(plan["status"], "PLANNED", plan["blockers"])
        selected = {row["path"] for row in plan["files"] if row["state"] in ("INCLUDE", "TRANSFORM")}
        self.assertEqual(selected, {"LICENSE", "README.md", *expected})
        self.assertEqual(plan["plan_sha256"], analyze(self.source)["plan_sha256"])
        archives = []
        for name in ("first", "second"):
            output = self.base / name
            assemble(self.source, plan, output)
            archives.append((output / "release.zip").read_bytes())
        self.assertEqual(*archives)
        root = self.base / "extracted"
        extract_verified(archives[0], root)
        if command:
            env = dict(os.environ, PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1")
            env.pop("PYTHONPATH", None)
            result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
        return plan, root

    def test_package_resource_cli_default(self):
        self.put("kit/__init__.py", "")
        self.put("kit/data/defaults.json", '{"answer": 42}')
        self.put("kit/__main__.py", 'from importlib.resources import files\nimport json\nassert json.loads(files("kit").joinpath("data", "defaults.json").read_text())["answer"] == 42\n')
        self.planned({"kit/__init__.py", "kit/__main__.py", "kit/data/defaults.json"}, command=[sys.executable, "-m", "kit"])

    def test_custom_package_dir_native_declarations(self):
        self.put("pyproject.toml", '[project]\nname="kit"\nversion="1"\nlicense-files=["legal/*.txt"]\n[tool.setuptools.package-dir]\n""="lib"\n[tool.setuptools.package-data]\nkit=["data/*.json"]\n[tool.setuptools.data-files]\n"share/kit"=["shared/schema.dat"]\n')
        self.put("lib/kit/__init__.py", "")
        self.put("lib/kit/data/options.json", "{}")
        self.put("shared/schema.dat", "field,value\n")
        self.put("legal/NOTICE.txt", "Original synthetic fixture.\n")
        self.planned({"pyproject.toml", "lib/kit/__init__.py", "lib/kit/data/options.json", "shared/schema.dat", "legal/NOTICE.txt"})

    def test_binary_package_resource_is_kept(self):
        self.put("kit/__init__.py", "")
        self.put("main.py", 'from importlib import resources\nassert resources.files("kit").joinpath("table.bin").read_bytes() == bytes([0, 1, 2])\n')
        (self.source / "kit/table.bin").write_bytes(bytes([0, 1, 2]))
        self.planned({"kit/__init__.py", "kit/table.bin", "main.py"}, command=[sys.executable, "main.py"])

    def test_notebook_required_data_and_hidden_output(self):
        code = "import json\nassert json.load(open('data/input.json'))['value'] == 7\n"
        self.put("data/input.json", '{"value": 7}')
        self.put("study.ipynb", json.dumps({"nbformat": 4, "nbformat_minor": 5, "metadata": {}, "cells": [{"cell_type": "code", "source": code, "metadata": {}, "execution_count": 1, "outputs": [{"output_type": "stream", "name": "stdout", "text": "ghp_" + "X" * 30}]}]}))
        _, root = self.planned({"data/input.json", "study.ipynb"}, command=[sys.executable, "-c", "import json; exec(json.load(open('study.ipynb'))['cells'][0]['source'])"])
        self.assertEqual(json.loads((root / "study.ipynb").read_bytes())["cells"][0]["outputs"], [])

    def test_literal_plugin_with_ignored_untracked_settings(self):
        self.put(".gitignore", "settings.json\n")
        self.put("settings.json", '{"answer": 3}')
        self.put("plugins/__init__.py", "")
        self.put("plugins/worker.py", "def answer(): return 3\n")
        self.put("main.py", 'import importlib, json\nassert importlib.import_module("plugins.worker").answer() == json.load(open("settings.json"))["answer"]\n')
        self.planned({".gitignore", "settings.json", "plugins/__init__.py", "plugins/worker.py", "main.py"}, command=[sys.executable, "main.py"])

    @unittest.skipUnless(shutil.which("node"), "Node required for synthetic runtime")
    def test_nested_node_url_asset_default(self):
        self.put("apps/site/package.json", '{"type":"module","main":"web/main.mjs","files":["web"]}')
        self.put("apps/site/web/main.mjs", 'import {readFileSync} from "node:fs";\nif (readFileSync(new URL("./message.dat", import.meta.url), "utf8") !== "ready") throw Error("missing asset");\n')
        self.put("apps/site/web/message.dat", "ready")
        self.planned({"apps/site/package.json", "apps/site/web/main.mjs", "apps/site/web/message.dat"}, command=[shutil.which("node"), "apps/site/web/main.mjs"])

    def test_source_workflow_metadata_and_generated_logs(self):
        self.put("main.py", "from pathlib import Path\nPath('generated.json').write_text('{}')\n")
        self.put(".github/workflows/check.yml", "name: Check\non: push\njobs: {}\n")
        self.put("run.log", "synthetic temporary log\n")
        self.put("__pycache__/main.pyc", "cache")
        self.planned({"main.py", ".github/workflows/check.yml"}, command=[sys.executable, "main.py"])

    def test_config_plugin_remains_unresolved(self):
        self.put("settings.json", '{"plugin": "plugins.worker"}')
        self.put("main.py", 'import importlib, json\nconfig=json.load(open("settings.json"))\nimportlib.import_module(config["plugin"])\n')
        plan = analyze(self.source)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("dynamic-import", {b["code"] for b in plan["blockers"]})

    def test_missing_package_input_blocks(self):
        self.put("kit/__init__.py", "")
        self.put("main.py", 'from importlib.resources import files\nfiles("kit").joinpath("missing.json").read_text()\n')
        plan = analyze(self.source)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("missing-resource", {b["code"] for b in plan["blockers"]})

    def test_package_declaration_does_not_bypass_secret(self):
        self.put("kit/__init__.py", "")
        self.put("main.py", 'from importlib.resources import files\nfiles("kit").joinpath("settings.json").read_text()\n')
        self.put("kit/settings.json", json.dumps({"token": "ghp_" + "X" * 30}))
        plan = analyze(self.source)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("sensitive-content", {b["code"] for b in plan["blockers"]})

    def test_unrelated_json_still_requires_decision(self):
        self.put("main.py", "assert True\n")
        self.put("unknown.json", "{}")
        plan = analyze(self.source)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("unclassified-resource", {b["code"] for b in plan["blockers"]})

    def test_resource_alias_and_division(self):
        self.put("kit/__init__.py", "")
        self.put("kit/value.json", "{}")
        self.put("main.py", 'from importlib.resources import files as package_files\nassert (package_files(package="kit") / "value.json").read_text() == "{}"\n')
        self.planned({"kit/__init__.py", "kit/value.json", "main.py"}, command=[sys.executable, "main.py"])

    def test_dynamic_or_shadowed_package_anchor_blocks(self):
        self.put("kit/__init__.py", "")
        self.put("kit/x.json", "{}")
        for code in (
            'from importlib.resources import files\nfiles(package_name).joinpath("x.json").read_text()',
            'from importlib.resources import files\nfiles = arbitrary_loader\nfiles("kit").joinpath("x.json").read_text()',
            'from importlib.resources import files\ndef read(files):\n return files("kit").joinpath("x.json").read_text()',
            'from importlib.resources import files\nfrom another_module import files\nfiles("kit").joinpath("x.json").read_text()',
            'from importlib.resources import files\nfrom another_module import *\nfiles("kit").joinpath("x.json").read_text()',
        ):
            with self.subTest(code=code):
                self.put("main.py", code)
                self.assertEqual(analyze(self.source)["status"], "BLOCKED")

    def test_binary_secret_never_promoted(self):
        self.put("main.py", 'from pathlib import Path\nPath("data.bin").read_bytes()\n')
        (self.source / "data.bin").write_bytes(b"\x00ghp_" + b"X" * 30)
        plan = analyze(self.source)
        row = next(r for r in plan["files"] if r["path"] == "data.bin")
        self.assertEqual(row["reason"], "sensitive-content")
        self.assertEqual(plan["status"], "BLOCKED")

    def test_required_binary_exclusion_stays_blocked(self):
        self.put("main.py", 'from pathlib import Path\nPath("data.bin").read_bytes()\n')
        (self.source / "data.bin").write_bytes(bytes([0, 1]))
        plan = analyze(self.source, {"exclude": ["data.bin"]})
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("dependency-not-included", {b["code"] for b in plan["blockers"]})

    def test_glob_does_not_promote_hidden_or_nested_junk(self):
        self.put("kit/__init__.py", "")
        self.put("kit/good.dat", "data")
        self.put("kit/.private.dat", "requires decision")
        self.put("kit/nested/junk.dat", "requires decision")
        self.put("pyproject.toml", '[tool.setuptools.package-data]\nkit=["*.dat"]\n')
        plan = analyze(self.source)
        states = {r["path"]: r["state"] for r in plan["files"]}
        self.assertEqual(states["kit/good.dat"], "INCLUDE")
        self.assertEqual(states["kit/.private.dat"], "UNRESOLVED")
        self.assertEqual(states["kit/nested/junk.dat"], "UNRESOLVED")

    def test_declared_missing_data_or_license_blocks(self):
        self.put("main.py", "assert True\n")
        for declaration in ('[tool.setuptools.data-files]\n"share/kit"=["missing.dat"]\n', '[project]\nlicense-files=["legal/*.license"]\n'):
            with self.subTest(declaration=declaration):
                self.put("pyproject.toml", declaration)
                plan = analyze(self.source)
                self.assertIn("missing-resource", {b["code"] for b in plan["blockers"]})

    def test_nested_node_missing_url_has_no_root_fallback(self):
        self.put("package.json", "{}")
        self.put("message.dat", "wrong location")
        self.put("web/main.mjs", 'import {readFileSync} from "node:fs"; readFileSync(new URL("./message.dat", import.meta.url));')
        plan = analyze(self.source)
        self.assertIn("missing-resource", {b["code"] for b in plan["blockers"]})

    def test_runtime_omits_workflow_but_source_keeps_it(self):
        self.put("main.py", "assert True\n")
        self.put(".github/workflows/check.yml", "name: Check\non: push\n")
        for mode, expected in (("source", "INCLUDE"), ("runtime", "EXCLUDE")):
            with self.subTest(mode=mode):
                plan = analyze(self.source, {"mode": mode})
                self.assertEqual(plan["status"], "PLANNED")
                self.assertEqual(next(r["state"] for r in plan["files"] if r["path"].endswith("check.yml")), expected)


if __name__ == "__main__":
    unittest.main()
