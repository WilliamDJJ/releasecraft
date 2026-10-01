"""Regressions for independent core-review findings."""

import json
import time
import unittest
import zipfile
import test_core
from releasecraft.build import MANIFEST, verify_archive
from releasecraft.safety import ReleaseError, canonical, digest, findings, relative
from releasecraft.policy import load_policy


class ReviewRegressions(unittest.TestCase):
    put = test_core.CoreTests.put
    setUp = test_core.CoreTests.setUp
    tearDown = test_core.CoreTests.tearDown
    output = test_core.CoreTests.output

    def test_dense_findings_are_bounded(self):
        start = time.monotonic()
        result = findings(((".".join(("10", "0", "0", "1")) + "\n") * 100000).encode())
        self.assertLessEqual(len(result), 129)
        self.assertLess(time.monotonic() - start, 10)
        self.assertIn(("finding-limit", 128), result)

    def test_windows_invalid_chars(self):
        for char in '"<>|?*':
            with self.subTest(char=char), self.assertRaises(ReleaseError):
                relative("bad" + char + ".txt")

    def test_policy_globs_still_allowed(self):
        self.assertEqual(
            load_policy(value={"include": ["assets/*.json"]})["include"],
            ["assets/*.json"],
        )

    def test_archive_prefix_conflict_rejected(self):
        archive = self.output()
        dest = self.base / "bad.zip"
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(dest, "w") as dst:
            manifest = json.loads(src.read(MANIFEST))
            for path in ("a", "a/b.txt"):
                blob = b"data"
                manifest["files"].append(
                    {"path": path, "sha256": digest(blob), "size": 4, "mode": 420}
                )
                info = zipfile.ZipInfo(path)
                info.external_attr = 0o100644 << 16
                dst.writestr(info, blob)
            for info in src.infolist():
                dst.writestr(
                    info,
                    canonical(manifest)
                    if info.filename == MANIFEST
                    else src.read(info),
                )
        self.assertEqual(verify_archive(dest)["status"], "FAILED")

    def test_integrity_error_redacts_sensitive_filename(self):
        archive = self.output()
        dest = self.base / "bad.zip"
        secret = "gh" + "p_" + "A" * 32
        with zipfile.ZipFile(archive) as src, zipfile.ZipFile(dest, "w") as dst:
            manifest = json.loads(src.read(MANIFEST))
            manifest["files"].append(
                {"path": secret, "sha256": "0" * 64, "size": 4, "mode": 420}
            )
            info = zipfile.ZipInfo(secret)
            info.external_attr = 0o100644 << 16
            dst.writestr(info, b"data")
            for info in src.infolist():
                dst.writestr(
                    info,
                    canonical(manifest)
                    if info.filename == MANIFEST
                    else src.read(info),
                )
        result = verify_archive(dest)
        self.assertEqual(result["status"], "FAILED")
        self.assertNotIn(secret, json.dumps(result))

    def test_nonobject_manifest_returns_failed(self):
        for value in ([], None):
            archive = self.base / "bad.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(MANIFEST, canonical(value))
            self.assertEqual(verify_archive(archive)["status"], "FAILED")

    def test_research_default_preserves_outputs(self):
        self.assertEqual(
            load_policy(value={"mode": "research"})["notebook_outputs"], "preserve"
        )

    def test_cache_matches_active_plan(self):
        from releasecraft.analyze import analyze
        from releasecraft.build import verify_cached

        plan = analyze(self.source)
        archive = self.output()
        self.assertEqual(verify_cached(archive, plan)["status"], "CANDIDATE")
        self.put("main.py", 'print("changed")')
        with self.assertRaises(ReleaseError):
            verify_cached(archive, analyze(self.source))
