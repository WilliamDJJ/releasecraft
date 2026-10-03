"""Small synthetic fixtures and logical payload mocks for global scan bounds."""

import contextlib
import importlib
import json
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from releasecraft.build import assemble
from releasecraft.diagnostics import blocker_summary
from releasecraft.safety import ReleaseError

analysis = importlib.import_module("releasecraft.analyze")


class ScanLimitTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "source"
        self.root.mkdir()

    def put(self, name, data=b"x"):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def inventory(self, **limits):
        audit = {}
        with contextlib.ExitStack() as stack:
            for key, value in limits.items():
                stack.enter_context(patch.object(analysis, key, value))
            files, ignored, errors = analysis.inventory(self.root, 1024, audit=audit)
        return files, ignored, errors, audit

    def project(self, code=b"assert True\n"):
        self.put("LICENSE", b"MIT License\nPermission is hereby granted\n")
        self.put("README.md", b"# Synthetic component\n")
        self.put("main.py", code)

    def test_success_counts_files_directories_and_pruning(self):
        self.put("main.py", b"pass")
        self.put("child/a.txt", b"abc")
        self.put(".venv/private.txt", b"not scanned")
        files, ignored, errors, audit = self.inventory()
        self.assertEqual(set(files), {"main.py", "child/a.txt"})
        self.assertEqual(len(ignored), 1)
        self.assertEqual(errors, [])
        self.assertEqual(audit["entries_observed"], 4)
        self.assertEqual(audit["entries_processed"], 4)
        self.assertEqual(audit["bytes_reserved"], 9)
        self.assertEqual(audit["bytes_retained"], 7)
        self.assertTrue(audit["complete"])

    def test_successful_entries_cannot_evade_global_cap(self):
        for name in ("a/1.txt", "a/2.txt", "b/1.txt", "b/2.txt", "c/1.txt"):
            self.put(name)
        files, _, errors, audit = self.inventory(MAX_SCAN_ENTRIES=5)
        self.assertEqual(set(files), {"a/1.txt", "a/2.txt"})
        self.assertEqual(audit["entries_observed"], 6)
        self.assertEqual(audit["read_attempts"], 2)
        self.assertEqual(errors[-1]["code"], "scan-entry-limit")
        self.assertFalse(audit["complete"])

    def test_unreadable_entries_count_and_stop_other_branches(self):
        for name in ("a/1.txt", "a/2.txt", "b/1.txt", "b/2.txt", "c/1.txt"):
            self.put(name)
        with patch.object(analysis, "snapshot", side_effect=PermissionError("private diagnostic")) as read:
            _, _, errors, audit = self.inventory(MAX_SCAN_ENTRIES=5)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(audit["errors_observed"], 2)
        self.assertEqual(audit["entries_observed"], 6)
        self.assertEqual(errors[-1]["code"], "scan-entry-limit")
        self.assertNotIn("private diagnostic", json.dumps(errors))

    def test_huge_directory_enumeration_is_bounded_and_not_partially_read(self):
        yielded = []

        def stream(reverse=False):
            for number in range(1000000):
                yielded.append(number)
                name = f"file-{999999-number if reverse else number}.txt"
                yield SimpleNamespace(name=name, path=str(self.root / name))

        reports = []
        for reverse in (False, True):
            yielded.clear()
            with (
                patch.object(analysis.os, "scandir", return_value=contextlib.nullcontext(stream(reverse))),
                patch.object(analysis, "snapshot") as read,
            ):
                files, _, errors, audit = self.inventory(MAX_DIRECTORY_ENTRIES=3)
            self.assertEqual(len(yielded), 4)
            read.assert_not_called()
            self.assertEqual(files, {})
            self.assertEqual(errors, [{"code": "scan-directory-entry-limit", "inventory_complete": False}])
            reports.append(audit)
        self.assertEqual(reports[0], reports[1])

    def test_logical_large_payloads_reserve_budget_before_reads(self):
        logical_size = 16 * 1024 * 1024
        root = self.root.resolve()

        class Payload:
            cached = None
            size = logical_size

        class Entry:
            def __init__(self, number):
                self.name = f"{number:02}.bin"
                self.path = str(root / self.name)

            def stat(self, follow_symlinks=False):
                return SimpleNamespace(st_mode=stat.S_IFREG, st_size=logical_size, st_nlink=1, st_file_attributes=0)

        audit = {}
        with (
            patch.object(analysis.os, "scandir", return_value=contextlib.nullcontext(iter(Entry(i) for i in range(32)))),
            patch.object(analysis, "snapshot", return_value=Payload()) as read,
            patch.object(analysis, "MAX_SCAN_BYTES", 256 * 1024 * 1024),
        ):
            files, _, errors = analysis.inventory(self.root, logical_size, audit=audit)
        self.assertEqual(read.call_count, 15)
        self.assertEqual(len(files), 15)
        self.assertEqual(audit["bytes_reserved"], 15 * (logical_size + 1))
        self.assertLessEqual(audit["bytes_reserved"], 256 * 1024 * 1024)
        self.assertEqual(errors[-1]["code"], "scan-byte-limit")

    def test_failed_reads_do_not_refund_possible_consumed_bytes(self):
        for name in ("a.txt", "b.txt", "c.txt"):
            self.put(name, b"1234")
        with patch.object(analysis, "snapshot", side_effect=OSError("synthetic")) as read:
            _, _, errors, audit = self.inventory(MAX_SCAN_BYTES=10)
        self.assertEqual(read.call_count, 2)
        self.assertEqual(audit["bytes_reserved"], 10)
        self.assertEqual(audit["bytes_retained"], 0)
        self.assertEqual(errors[-1]["code"], "scan-byte-limit")

    def test_nested_byte_limit_propagates_globally(self):
        self.put("a/first.txt", b"1234")
        self.put("a/second.txt", b"1234")
        self.put("b/later.txt", b"1234")
        files, _, errors, audit = self.inventory(MAX_SCAN_BYTES=5)
        self.assertEqual(list(files), ["a/first.txt"])
        self.assertEqual(audit["read_attempts"], 1)
        self.assertEqual(audit["directories_enumerated"], 2)
        self.assertEqual(errors[-1]["code"], "scan-byte-limit")

    def test_oversized_file_is_rejected_from_metadata(self):
        self.put("large.bin", b"12345")
        audit = {}
        with patch.object(analysis, "snapshot") as read:
            _, _, errors = analysis.inventory(self.root, 4, audit=audit)
        read.assert_not_called()
        self.assertEqual(audit["bytes_reserved"], 0)
        self.assertEqual(errors[0]["code"], "unsafe-or-unreadable-file")

    def test_metadata_size_disagreement_is_not_retained(self):
        self.put("main.py", b"pass")
        with patch.object(analysis, "snapshot", side_effect=ReleaseError("Source changed during read")) as read:
            files, _, errors, audit = self.inventory()
        self.assertEqual(read.call_args.args[2], 4)
        self.assertEqual(files, {})
        self.assertEqual(audit["bytes_retained"], 0)
        self.assertEqual(errors[0]["code"], "unsafe-or-unreadable-file")

    def test_inventory_diagnostics_are_capped_and_redacted(self):
        for number in range(8):
            self.put(f"{number}.txt")
        with patch.object(analysis, "snapshot", side_effect=PermissionError("private message")) as read:
            _, _, errors, audit = self.inventory(MAX_INVENTORY_ERRORS=2)
        self.assertEqual(read.call_count, 3)
        self.assertEqual(len(errors), 3)
        self.assertEqual(audit["error_details_retained"], 2)
        self.assertEqual(audit["error_details_omitted_at_least"], 1)
        self.assertEqual(errors[-1]["code"], "scan-diagnostic-limit")
        self.assertNotIn("private message", json.dumps(errors))

    def test_directory_permission_error_is_a_redacted_incomplete_plan(self):
        with patch.object(analysis.os, "scandir", side_effect=PermissionError("private directory")):
            plan = analysis.analyze(self.root)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertFalse(plan["scan"]["traversal_complete"])
        self.assertIn("unreadable-directory", [r["code"] for r in plan["blockers"]])
        self.assertNotIn("private directory", json.dumps(plan))

    def test_partial_directory_iteration_is_discarded(self):
        def entries():
            yield SimpleNamespace(name="a.txt", path=str(self.root / "a.txt"))
            raise PermissionError("private enumeration failure")

        with (
            patch.object(analysis.os, "scandir", return_value=contextlib.nullcontext(entries())),
            patch.object(analysis, "snapshot") as read,
        ):
            files, _, errors, audit = self.inventory()
        self.assertEqual(files, {})
        read.assert_not_called()
        self.assertFalse(audit["traversal_complete"])
        self.assertEqual(audit["entries_observed"], 1)
        self.assertEqual(errors[0]["code"], "unreadable-directory")

    def test_depth_limit_is_iterative_and_blocks(self):
        self.put("a/b/c/d.txt")
        with patch.object(analysis, "MAX_SCAN_DEPTH", 2):
            plan = analysis.analyze(self.root)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertEqual(plan["scan"]["stop_reason"], "scan-depth-limit")

    def test_incomplete_inventory_cannot_build(self):
        self.project()
        with patch.object(analysis, "MAX_SCAN_ENTRIES", 1):
            plan = analysis.analyze(self.root)
            self.assertEqual(plan["status"], "BLOCKED")
            self.assertFalse(plan["scan"]["complete"])
            with self.assertRaises(ReleaseError):
                assemble(self.root, plan, self.base / "out")
        self.assertFalse((self.base / "out").exists())

    def test_evidence_limit_retains_partial_graph_and_blocks(self):
        self.project(b"open(name)\n" * 20)
        with patch.object(analysis, "MAX_ANALYSIS_EVIDENCE", 5):
            plan = analysis.analyze(self.root)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertFalse(plan["analysis"]["complete"])
        self.assertEqual(plan["analysis"]["evidence_items_retained"], 5)
        self.assertEqual(plan["analysis"]["details_omitted_at_least"], 1)
        self.assertEqual(len(plan["dependencies"]["main.py"]["unresolved"]), 5)
        self.assertEqual(plan["blockers"][-1]["code"], "analysis-evidence-limit")
        self.assertFalse(plan["blocker_summary"]["counts_complete"])

    def test_evidence_limit_preserves_all_retained_inventory_hashes(self):
        self.project()
        self.put("a.py", b"open(name)\n" * 10)
        with patch.object(analysis, "MAX_ANALYSIS_EVIDENCE", 2):
            limited = analysis.analyze(self.root)
        complete = analysis.analyze(self.root)
        self.assertEqual(limited["snapshot_sha256"], complete["snapshot_sha256"])
        pending = next(row for row in limited["files"] if row["path"] == "main.py")
        self.assertEqual(pending["state"], "UNRESOLVED")
        self.assertEqual(pending["reason"], "analysis-incomplete")

    def test_parser_recursion_limit_is_an_incomplete_redacted_plan(self):
        self.project()
        with patch.object(analysis, "dependencies", side_effect=RecursionError("private parser detail")):
            plan = analysis.analyze(self.root)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertEqual(plan["analysis"]["stop_reason"], "analysis-depth-limit")
        self.assertFalse(plan["analysis"]["complete"])
        self.assertEqual(len(plan["files"]), 3)
        self.assertNotIn("private parser detail", json.dumps(plan))

    def test_summary_counts_and_actions_are_stable(self):
        items = [{"code": "missing-resource"}, {"code": "sensitive-content"}, {"code": "missing-resource"}]
        first = blocker_summary(items, True)
        self.assertEqual(first, blocker_summary(list(reversed(items)), True))
        self.assertEqual([(r["code"], r["count"]) for r in first["groups"]], [("missing-resource", 2), ("sensitive-content", 1)])
        self.assertIn("Remove", first["groups"][1]["next_action"])

    def test_native_resource_diagnostics_stop_at_shared_budget(self):
        self.project()
        self.put("MANIFEST.in", b"include *.txt\n" * 20)
        self.put("a.txt")
        with patch.object(analysis, "MAX_ANALYSIS_EVIDENCE", 5):
            plan = analysis.analyze(self.root)
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertEqual(plan["analysis"]["evidence_items_retained"], 5)
        self.assertEqual(len(plan["dependencies"]["MANIFEST.in"]["edges"]), 5)
        self.assertEqual(plan["blockers"][-1]["code"], "analysis-evidence-limit")

    def test_cli_summary_preserves_full_private_plan(self):
        self.project(b"open(name)\n")
        work = self.base / "work"
        result = subprocess.run([sys.executable, "-m", "releasecraft", "plan", str(self.root), "--work", str(work)], capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 2)
        summary = json.loads(result.stdout)
        plan = json.loads((work / "plan.json").read_bytes())
        self.assertNotIn("files", summary)
        self.assertEqual(summary["plan_sha256"], plan["plan_sha256"])
        self.assertTrue(plan["dependencies"]["main.py"]["unresolved"])
        detailed = subprocess.run([sys.executable, "-m", "releasecraft", "plan", str(self.root), "--work", str(self.base / "detailed"), "--details"], capture_output=True, timeout=30)
        self.assertEqual(json.loads(detailed.stdout), plan)

    def test_inventory_preserves_content_mtime_and_repeat_identity(self):
        self.project()
        files = sorted(self.root.iterdir())
        before = [(p.name, p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        first = analysis.analyze(self.root)
        second = analysis.analyze(self.root)
        after = [(p.name, p.read_bytes(), p.stat().st_mtime_ns) for p in files]
        self.assertEqual(before, after)
        self.assertEqual(first, second)


if __name__ == "__main__":
    unittest.main()
