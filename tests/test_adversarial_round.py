"""Independent synthetic file-set and metamorphic delivery checks."""
import json
import os
import subprocess
import unittest
from unittest.mock import patch
import zipfile

import test_core
from releasecraft.analyze import analyze, freeze
from releasecraft.build import MANIFEST, assemble, verify_archive
from releasecraft.safety import ReleaseError


class AdversarialTests(unittest.TestCase):
    setUp = test_core.CoreTests.setUp
    tearDown = test_core.CoreTests.tearDown
    put = test_core.CoreTests.put
    plan = test_core.CoreTests.plan
    base_files = {"LICENSE", "README.md", "main.py"}

    def release(self, expected, policy=None, name="release"):
        plan = analyze(self.source, policy)
        self.assertEqual(plan["status"], "PLANNED", plan["blockers"])
        selected = {r["path"] for r in plan["files"] if r["state"] in ("INCLUDE", "TRANSFORM")}
        self.assertEqual(selected, expected)
        output = self.base / name
        assemble(self.source, plan, output)
        archive = output / "release.zip"
        self.assertEqual(verify_archive(archive)["status"], "CANDIDATE")
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(set(z.namelist()), expected | {MANIFEST})
        return archive

    def test_required_json_vs_unrelated_json_exact_set(self):
        self.put("main.py", "import json\njson.load(open(file='required.json'))\n")
        self.put("required.json", '{"version": 1}')
        self.put("scratch.json", '{"debug": true}')
        self.assertEqual(self.plan()["status"], "BLOCKED")
        self.release(self.base_files | {"required.json"}, {"exclude": ["scratch.json"]})

    def test_path_constructor_components_are_all_resolved(self):
        self.put("assets/needed.json", "{}")
        for index, expression in enumerate((
            "Path('assets', 'needed.json')",
            "Path('assets') / 'needed.json'",
            "Path('assets').joinpath('needed.json')",
        )):
            with self.subTest(expression=expression):
                self.put("main.py", f"from pathlib import Path\n{expression}.read_text()\n" if index != 1 else f"from pathlib import Path\n({expression}).read_text()\n")
                self.release(self.base_files | {"assets/needed.json"}, name=f"paths-{index}")

    def test_hash_character_in_literal_file_is_not_url_fragment(self):
        for name in ("data#revision.json", "#revision.json"):
            self.put(name, "{}")
            for index, code in enumerate((
                f"open({name!r}).read()",
                f"from pathlib import Path\nPath({name!r}).read_bytes()",
            )):
                with self.subTest(code=code):
                    self.put("main.py", code)
                    self.release(self.base_files | {name}, name=f"hash-{name}-{index}")
            (self.source / name).unlink()
        self.put("README.md", "[section](#section)\n[page](guide.md#section)\n")
        self.put("guide.md", "# section\n")
        self.put("main.py", "print('safe')")
        self.release(self.base_files | {"guide.md"}, name="document-fragment")

    def test_git_metadata_cannot_hide_required_untracked_data(self):
        self.put(".gitignore", "assets/\n")
        self.put(".git/HEAD", "ref: refs/heads/main\n")
        self.put("assets/needed.json", "{}")
        self.put("main.py", "open('assets/needed.json').read()")
        self.release(self.base_files | {".gitignore", "assets/needed.json"})

    def test_dynamic_declaration_still_checks_exclusions_and_absence(self):
        self.put("main.py", "open(selected_name).read()")
        self.put("data/needed.json", "{}")
        self.assertEqual(self.plan()["status"], "BLOCKED")
        declared = {"dynamic_resources": {"main.py": ["data/needed.json"]}}
        self.release(self.base_files | {"data/needed.json"}, declared)
        excluded = self.plan(**declared, exclude=["data/needed.json"])
        self.assertIn("dependency-not-included", {b["code"] for b in excluded["blockers"]})
        missing = self.plan(dynamic_resources={"main.py": ["data/absent.json"]})
        self.assertIn("missing-resource", {b["code"] for b in missing["blockers"]})

    def test_typescript_json_css_and_native_assets_exact_set(self):
        self.put("package.json", '{"main":"src/app.ts","files":["public/theme.dat"]}')
        self.put("src/app.ts", "import config from './data.json';\n")
        self.put("src/data.json", "{}")
        self.put("public/style.css", "body { background: url('./theme.dat'); }\n")
        self.put("public/theme.dat", "synthetic theme")
        self.put("public/junk.dat", "unrelated")
        expected = self.base_files | {"package.json", "src/app.ts", "src/data.json", "public/style.css", "public/theme.dat"}
        self.release(expected, {"exclude": ["public/junk.dat"]})

    def test_missing_node_entrypoints_are_not_planned(self):
        for field in ("main", "module", "types", "typings", "bin"):
            with self.subTest(field=field):
                self.put("package.json", json.dumps({field: "missing.js"}))
                plan = self.plan()
                self.assertEqual(plan["status"], "BLOCKED")
                self.assertIn("missing-resource", {b["code"] for b in plan["blockers"]})
                self.put("missing.js", "export const value = 1;")
                self.release(self.base_files | {"package.json", "missing.js"}, name=field)
                (self.source / "missing.js").unlink()

    def test_nested_node_resource_is_relative_to_its_manifest(self):
        self.put("component/package.json", '{"files":["assets/*.dat"]}')
        self.put("component/assets/required.dat", "required")
        self.put("assets/unrelated.dat", "unrelated")
        expected = self.base_files | {"component/package.json", "component/assets/required.dat"}
        self.release(expected, {"exclude": ["assets/unrelated.dat"]})

    def test_required_python_metadata_file_must_exist(self):
        for index, (declaration, resource) in enumerate((
            ('readme = "GUIDE.md"', "GUIDE.md"),
            ('readme = {file="GUIDE.md", content-type="text/markdown"}', "GUIDE.md"),
            ('license = {file="COPYING.extra"}', "COPYING.extra"),
        )):
            with self.subTest(declaration=declaration):
                self.put("pyproject.toml", "[project]\n" + declaration + "\n")
                plan = self.plan()
                self.assertEqual(plan["status"], "BLOCKED")
                self.assertIn("missing-resource", {b["code"] for b in plan["blockers"]})
                self.put(resource, "Synthetic metadata text\n")
                self.release(self.base_files | {"pyproject.toml", resource}, name=f"metadata-{index}")
                (self.source / resource).unlink()
        self.put("pyproject.toml", '[project]\nlicense = "Apache-2.0"\n')
        self.release(self.base_files | {"pyproject.toml"}, name="license-expression")

    def test_native_resource_declaration_does_not_override_exclusion(self):
        self.put("package.json", '{"files":["assets/required.dat"]}')
        self.put("assets/required.dat", "required")
        plan = self.plan(exclude=["assets/required.dat"])
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("dependency-not-included", {b["code"] for b in plan["blockers"]})

    def test_notebook_output_strip_does_not_hide_metadata_secret(self):
        token = "gh" + "p_" + "A" * 32
        notebook = {"nbformat": 4, "metadata": {}, "cells": [
            {"cell_type": "code", "source": ["print(1)"], "metadata": {},
             "execution_count": 1, "outputs": [{"output_type": "stream", "text": token}]}
        ]}
        self.put("study.ipynb", json.dumps(notebook))
        archive = self.release(self.base_files | {"study.ipynb"})
        with zipfile.ZipFile(archive) as z:
            self.assertNotIn(token.encode(), z.read("study.ipynb"))
        notebook["cells"][0]["metadata"]["hidden"] = token
        self.put("study.ipynb", json.dumps(notebook))
        plan = self.plan(include=["study.ipynb"])
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertNotIn(token, json.dumps(plan))

    def test_unicode_space_and_mixed_case_names_survive_archive(self):
        name = "资产 表/MixCase.json"
        self.put(name, '{"unit": 1}')
        self.put("main.py", f"open({name!r}).read()")
        archive = self.release(self.base_files | {name})
        with zipfile.ZipFile(archive) as z:
            self.assertEqual(z.read(name), b'{"unit": 1}')

    def test_normalized_output_recursion_cannot_be_policy_excluded(self):
        nested = self.source / ".." / self.source.name / "ignored-work"
        with self.assertRaises(ReleaseError):
            freeze(self.source, nested, {"exclude": ["ignored-work/**"]})
        self.assertFalse((self.source / "ignored-work").exists())

    @unittest.skipUnless(os.name == "nt", "Windows junction alias boundary")
    def test_junction_alias_cannot_hide_source_output_overlap(self):
        alias = self.base / "source alias"
        result = subprocess.run(["cmd", "/d", "/c", "mklink", "/J", str(alias), str(self.source)], capture_output=True, timeout=10)
        if result.returncode:
            self.skipTest("Junction creation unavailable")
        with self.assertRaises(ReleaseError):
            freeze(self.source, alias / "work")
        self.assertFalse((self.source / "work").exists())

    def test_excluded_file_mutation_during_staging_invalidates_build(self):
        import releasecraft.build as builder
        self.put("excluded.txt", "before")
        plan = self.plan(exclude=["excluded.txt"])
        original = builder.read_safe

        def mutate(root, rel, limit):
            result = original(root, rel, limit)
            if rel == "main.py":
                self.put("excluded.txt", "after!")
            return result

        with patch.object(builder, "read_safe", side_effect=mutate):
            with self.assertRaises(ReleaseError):
                assemble(self.source, plan, self.base / "out")
        self.assertFalse((self.base / "out").exists())
        self.assertFalse(list(self.base.glob(".releasecraft-stage-*")))

    def test_frozen_plan_replays_after_mtime_only_and_directory_relocation(self):
        self.put("main.py", "open('required.json').read()")
        self.put("required.json", "{}")
        expected = self.base_files | {"required.json"}
        freeze(self.source, self.base / "work")
        plan = json.loads((self.base / "work/plan.json").read_bytes())
        other = self.base / "重放 source"
        for path in sorted(self.source.rglob("*"), reverse=True):
            if path.is_file():
                target = other / path.relative_to(self.source)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
                os.utime(target, ns=(1000000000000000000, 1000000000000000000))
        self.assertEqual(analyze(other)["plan_sha256"], plan["plan_sha256"])
        first = self.release(expected)
        assemble(other, plan, self.base / "replayed")
        self.assertEqual(first.read_bytes(), (self.base / "replayed/release.zip").read_bytes())

    def test_secret_cannot_be_promoted_or_excluded_while_required(self):
        token = "gh" + "p_" + "B" * 32
        self.put("credential.txt", token)
        self.put("main.py", "open('credential.txt').read()")
        for policy in ({"include": ["credential.txt"]}, {"resources": ["credential.txt"]}, {"exclude": ["credential.txt"]}):
            with self.subTest(policy=policy):
                plan = analyze(self.source, policy)
                self.assertEqual(plan["status"], "BLOCKED")
                self.assertNotIn(token, json.dumps(plan))
        self.put("main.py", "print('safe')")
        self.release(self.base_files, {"exclude": ["credential.txt"]})

    def test_nested_manifest_selects_local_literal_resource(self):
        self.put("component/MANIFEST.in", "include required.dat\n")
        self.put("component/required.dat", "required")
        self.put("required.dat", "unrelated")
        expected = self.base_files | {"component/MANIFEST.in", "component/required.dat"}
        self.release(expected, {"exclude": ["required.dat"]})

    def test_unknown_path_component_remains_blocked(self):
        self.put("assets/needed.json", "{}")
        self.put("main.py", "from pathlib import Path\nPath('assets', selected).read_text()")
        plan = self.plan()
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertIn("dynamic-pathlib-resource", {b["code"] for b in plan["blockers"]})

    def test_missing_native_references_share_evidence_budget(self):
        import importlib
        analysis = importlib.import_module("releasecraft.analyze")
        self.put("package.json", json.dumps({"bin": {f"cmd{i}": f"missing{i}.js" for i in range(20)}}))
        with patch.object(analysis, "MAX_ANALYSIS_EVIDENCE", 3):
            plan = self.plan()
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertFalse(plan["analysis"]["complete"])
        self.assertEqual(plan["analysis"]["evidence_items_retained"], 3)
        self.assertEqual(plan["blockers"][-1]["code"], "analysis-evidence-limit")
