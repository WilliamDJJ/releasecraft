"""Literal npm preferences and non-overridable config safety contracts."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from releasecraft.analyze import analyze
from releasecraft.build import assemble, verify_archive
from releasecraft.safety import ReleaseError, canonical, digest


class NpmConfigTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="releasecraft npm config ")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / "source"
        self.source.mkdir()
        self.put("LICENSE", "Permission is hereby granted, free of charge.\n")
        self.put("README.md", "# Synthetic package\n")
        self.put("package.json", '{"name":"fixture","version":"1.0.0","main":"index.js"}')
        self.put("index.js", "export const answer = 42;\n")

    def put(self, name, content):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content.encode() if isinstance(content, str) else content)
        return path

    def config_row(self, content, policy=None, name=".npmrc"):
        self.put(name, content)
        plan = analyze(self.source, policy)
        return plan, next(row for row in plan["files"] if row["path"] == name)

    def assert_blocked(self, content, policy=None):
        plan, row = self.config_row(content, policy)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertEqual(row["state"], "UNRESOLVED")
        self.assertIn(row["reason"], ("npm-config-needs-review", "sensitive-content"))
        return plan

    def test_package_lock_false_is_default_source_and_reproducible(self):
        plan, row = self.config_row("package-lock=false\n")
        self.assertEqual(plan["status"], "PLANNED")
        self.assertEqual(row["state"], "INCLUDE")
        self.assertEqual({x["path"] for x in plan["files"]}, {"LICENSE", "README.md", "package.json", "index.js", ".npmrc"})
        self.assertEqual(plan, analyze(self.source))
        archives = []
        for i in range(2):
            out = self.base / str(i)
            assemble(self.source, plan, out)
            blob = (out / "release.zip").read_bytes()
            archives.append(blob)
            self.assertEqual(verify_archive(blob)["status"], "CANDIDATE")
            with zipfile.ZipFile(out / "release.zip") as archive:
                self.assertEqual(archive.read(".npmrc"), b"package-lock=false\n")
        self.assertEqual(*archives)

    def test_other_literal_preferences(self):
        for content in (
            "save-exact=true\nfund=false\nprogress=false\n",
            "package-lock-only=true\nformat-package-lock=false\n",
            "color=false\nunicode=true\nengine-strict=true\nprefer-dedupe=false\n",
            "lockfile-version=1\n", "lockfile-version=2\n", "lockfile-version=3\n",
        ):
            with self.subTest(content=content):
                self.assertEqual(self.config_row(content)[0]["status"], "PLANNED")

    def test_comments_whitespace_crlf_and_empty_noop(self):
        for content in ("", "# Package preferences\n; Reproducible metadata\n", " \tpackage-lock \t= false \t\r\n\r\n# Plain comment\r\n"):
            with self.subTest(content=content):
                self.assertEqual(self.config_row(content)[0]["status"], "PLANNED")

    def test_nested_and_case_variant_config(self):
        plan, row = self.config_row("package-lock=false\n", name="nested/.NPMRC")
        self.assertEqual(plan["status"], "PLANNED")
        self.assertEqual(row["state"], "INCLUDE")

    def test_invalid_and_ambiguous_forms_never_override(self):
        for content in (
            "package-lock", "package-lock=", "package-lock=0", "package-lock=FALSE",
            "package-lock='false'", "package-lock=false # inline", "package-lock=false;inline",
            "package-lock=false\npackage-lock=true", "package-lock[]=false", "[settings]\npackage-lock=false",
            "package-lock=false=extra", "package-lock=false\\\nfund=true", "PACKAGE-LOCK=false",
            "__proto__=false", "constructor=false", "lockfile-version=4", "lockfile-version=2.0",
            b"package-lock=false\x00", b"package-lock=false\xff", b"\xef\xbb\xbfpackage-lock=false",
            "package-lock=false\rfund=true", "package-lock=false\u2028fund=true",
        ):
            with self.subTest(content=repr(content)):
                self.assert_blocked(content, {"include": [".npmrc"]})

    def test_unknown_path_registry_and_execution_settings_require_review(self):
        for key, value in (
            ("unknown-preference", "true"), ("registry", "https://packages.example.invalid/"),
            ("@scope:registry", "https://packages.example.invalid/"), ("cache", "cache"),
            ("prefix", "local"), ("userconfig", "settings"), ("script-shell", "shell"),
            ("node-options", "--require=loader.js"), ("strict-ssl", "false"),
        ):
            for policy in ({}, {"include": [".npmrc"]}, {"resources": [".npmrc"]}):
                with self.subTest(key=key, policy=policy):
                    self.assert_blocked(key + "=" + value, policy)

    def test_auth_credential_key_variants_never_override(self):
        for key in (
            "_auth", "_authToken", "_AUTH_TOKEN", "auth-token", "_password", "password",
            "passwd", "token", "NPM_TOKEN", "NODE_AUTH_TOKEN", "username", "email",
            "//registry.example.invalid/:_authToken", "//registry.example.invalid/:_password",
            '"_authToken"', "keyfile", "certfile", "cafile",
        ):
            for policy in ({}, {"include": ["**"]}, {"resources": [".npmrc"]}):
                with self.subTest(key=key, policy=policy):
                    self.assert_blocked(key + "=" + "fixture-value", policy)

    def test_environment_references_are_not_expanded(self):
        with patch.dict("os.environ", {"RELEASECRAFT_FIXTURE": "false"}):
            for key in ("package-lock", "_authToken", "registry"):
                for value in ("${RELEASECRAFT_FIXTURE}", "${RELEASECRAFT_FIXTURE?}", "%RELEASECRAFT_FIXTURE%", "$RELEASECRAFT_FIXTURE"):
                    with self.subTest(key=key, value=value):
                        self.assert_blocked(key + "=" + value, {"include": [".npmrc"]})

    def test_credential_detection_survives_filename_change(self):
        for key in ("_auth", "_authToken", "_AUTH_TOKEN", "auth-token", "_password", "NPM_TOKEN", "NODE_AUTH_TOKEN", "//registry.example.invalid/:_authToken"):
            with self.subTest(key=key):
                self.put("settings.txt", key + "=" + "fixture-value")
                plan = analyze(self.source, {"include": ["settings.txt"]})
                row = next(x for x in plan["files"] if x["path"] == "settings.txt")
                self.assertEqual(row["reason"], "sensitive-content")
                self.assertEqual(plan["status"], "BLOCKED")
                self.assertNotIn("fixture-value", json.dumps(plan))

    def test_sensitive_comments_and_private_endpoint_stay_blocked(self):
        for content in (
            "# " + "_authToken" + "=" + "fixture-value\npackage-lock=false\n",
            "; registry=https://packages.example.invalid/\npackage-lock=false\n",
            "# ${HOME}\npackage-lock=false\n",
            "registry=http://" + "10." + "1.2.3/\n",
            "# " + "ghp_" + "X" * 30 + "\npackage-lock=false\n",
        ):
            with self.subTest(content=content):
                self.assert_blocked(content, {"include": [".npmrc"]})

    def test_native_file_declaration_cannot_promote_unsafe_config(self):
        self.put("package.json", '{"name":"fixture","files":[".npmrc"]}')
        plan = self.assert_blocked("registry=https://packages.example.invalid/\n")
        self.assertIn("dependency-not-included", {x["code"] for x in plan["blockers"]})

    def test_explicit_exclusion_does_not_publish_credentials(self):
        plan, row = self.config_row("_authToken" + "=" + "fixture-value", {"exclude": [".npmrc"]})
        self.assertEqual(plan["status"], "PLANNED")
        self.assertEqual(row["state"], "EXCLUDE")
        out = self.base / "without-config"
        assemble(self.source, plan, out)
        with zipfile.ZipFile(out / "release.zip") as archive:
            self.assertNotIn(".npmrc", archive.namelist())

    def test_config_bounds_fail_closed(self):
        for content in ("# " + "x" * 65536, "# line\n" * 257):
            self.assert_blocked(content, {"include": [".npmrc"]})

    def test_config_change_invalidates_frozen_plan(self):
        plan, _ = self.config_row("package-lock=false\n")
        self.put(".npmrc", "registry=https://packages.example.invalid/\n")
        with self.assertRaises(ReleaseError):
            assemble(self.source, plan, self.base / "changed")

    def test_archive_rechecks_config_independently(self):
        # Build without config, then insert a self-consistent unsafe config entry.
        out = self.base / "original"
        assemble(self.source, analyze(self.source), out)
        for i, content in enumerate(("_authToken" + "=" + "fixture-value", "registry=https://packages.example.invalid/", "package-lock=${ENV}")):
            changed = self.base / (str(i) + ".zip")
            blob = content.encode()
            with zipfile.ZipFile(out / "release.zip") as source, zipfile.ZipFile(changed, "w") as target:
                manifest = json.loads(source.read("RELEASE-MANIFEST.json"))
                manifest["files"].append({"path": ".npmrc", "sha256": digest(blob), "size": len(blob), "mode": 0o644})
                for info in source.infolist():
                    target.writestr(info, canonical(manifest) if info.filename == "RELEASE-MANIFEST.json" else source.read(info))
                info = zipfile.ZipInfo(".npmrc")
                info.external_attr = 0o100644 << 16
                target.writestr(info, blob)
            report = verify_archive(changed)
            self.assertEqual(report["status"], "FAILED")
            self.assertIn("npm-config-needs-review", {x["code"] for x in report["errors"]})
            self.assertNotIn("fixture-value", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
