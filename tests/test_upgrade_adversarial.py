"""Independent malformed-container, interruption and handoff boundary contracts."""
import io
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from releasecraft.analyze import analyze, freeze, plan_diff
from releasecraft.archive import frozen_archive, open_archive, member_index
from releasecraft.build import assemble, extract_verified, verify_archive
from releasecraft.managed import prepare
from releasecraft.operation import Operation, Cancelled
from releasecraft.review import decide, review_policy
from releasecraft.safety import ReleaseError, canonical, digest
from releasecraft.streaming import ContentScanner, PARSE_BYTES, SCAN_WINDOW


class UpgradeAdversarialTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.source = self.base / 'source 中文'
        self.source.mkdir()
        self.put('LICENSE', 'MIT License\nPermission is hereby granted\n')
        self.put('README.md', '# Reader\n')
        self.put('main.py', 'assert open("sample.csv").read().strip() == "1,2"\n')
        self.put('sample.csv', '1,2\n')

    def put(self, name, value):
        path = self.source / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value.encode() if isinstance(value, str) else value)
        return path

    def test_malformed_zip64_offset_is_failed_not_exception(self):
        for offset in (2**64-1, 2**63, 40):
            data = struct.pack('<4sLQL', b'PK\x06\x07', 0, offset, 1)
            data += struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 65535, 65535, 0xffffffff, 0xffffffff, 0)
            result = verify_archive(data)
            self.assertEqual(result['status'], 'FAILED')
            self.assertEqual(result['errors'][0]['code'], 'invalid-archive-or-manifest')

    def test_real_zip64_entry_count_does_not_claim_source_scan_capacity(self):
        # Actual ZIP64 directory with tiny payloads; no multi-gigabyte allocation.
        path = self.base / 'many.zip'
        with zipfile.ZipFile(path, 'w') as target:
            for i in range(65536):
                target.writestr(f'files/{i:05d}.txt', b'')
        with frozen_archive(path) as frozen, open_archive(frozen) as archive:
            self.assertEqual(len(member_index(archive)), 65536)
        self.assertEqual(verify_archive(path)['status'], 'FAILED')  # Missing manifest is still a gate.

    def test_directory_metadata_bomb_rejected_before_open(self):
        data = b'x' * 10 + struct.pack('<4s4H2LH', b'PK\x05\x06', 0, 0, 1, 1, 65*1024**2, 0, 0)
        with patch('releasecraft.archive.zipfile.ZipFile') as open_zip:
            self.assertEqual(verify_archive(data)['status'], 'FAILED')
            open_zip.assert_not_called()

    def test_expansion_bomb_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr('resource.bin', b'\0' * (2*1024**2))
        self.assertEqual(verify_archive(data.getvalue())['status'], 'FAILED')

    def test_large_structured_input_never_approved_from_prefix(self):
        self.put('main.py', 'import json\njson.load(open("input.json"))\n')
        self.put('input.json', '{"values":[' + ','.join('0' for _ in range(700)) + ']}')
        with patch('releasecraft.streaming.PARSE_BYTES', 1024), patch('releasecraft.analyze.PARSE_BYTES', 1024):
            plan = analyze(self.source)
        self.assertEqual(plan['status'], 'BLOCKED')
        self.assertIn('parser-file-limit', [r['code'] for r in plan['blockers']])

    def test_long_escaped_credential_context_cannot_fall_out_of_window(self):
        scanner = ContentScanner(PARSE_BYTES+1)
        scanner.feed(b'{"pass\\u0077ord":"' + b'x'*(SCAN_WINDOW*3) + b'"}')
        self.assertTrue(scanner.finish())

    def test_nested_private_auth_and_session_state_not_includable(self):
        names = ('module/playwright/.auth/state.json', 'module/.codex/sessions/run.json', 'module/.claude/settings.local.json')
        for name in names:
            self.put(name, '{}')
        plan = analyze(self.source, {'include': ['**/*.json']})
        self.assertEqual(plan['status'], 'PLANNED')
        for row in plan['files']:
            if row['path'] in names:
                self.assertEqual(row['state'], 'EXCLUDE')

    def test_built_archive_cannot_forge_private_file_approval(self):
        plan = analyze(self.source)
        assemble(self.source, plan, self.base/'release')
        changed = self.base/'changed.zip'
        rel = 'module/playwright/.auth/state.json'
        with zipfile.ZipFile(self.base/'release/release.zip') as before, zipfile.ZipFile(changed, 'w') as after:
            manifest = json.loads(before.read('RELEASE-MANIFEST.json'))
            manifest['files'].append({'path':rel, 'size':2, 'sha256':digest(b'{}'), 'mode':0o644})
            for info in before.infolist():
                after.writestr(info, canonical(manifest) if info.filename == 'RELEASE-MANIFEST.json' else before.read(info))
            info = zipfile.ZipInfo(rel)
            info.external_attr = 0o100644 << 16
            after.writestr(info, b'{}')
        result = verify_archive(changed)
        self.assertEqual(result['status'], 'FAILED')
        self.assertIn('private-agent-or-auth-state', [r['code'] for r in result['errors']])

    def test_cancel_during_public_copy_keeps_no_success_and_retains_unknown_partial(self):
        self.put('sample.csv', b'1,2\n'*300000)
        cancel = threading.Event()
        def event(value):
            if value['phase'] == 'Copying bytes' and value.get('current') == 'release.zip' and value.get('bytes_read', 0) > 0:
                cancel.set()
        result = prepare(self.source, operation=Operation(event, cancel, self.base/'state'))
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertFalse(list((self.source/'releasecraft-output').glob('release-*')))
        self.assertEqual(result.get('storage_warning'), 'public-pending-retained')
        self.assertEqual((self.source/'sample.csv').stat().st_size, 1200000)

    def test_extract_cancellation_removes_owned_stage_and_never_commits(self):
        plan = analyze(self.source)
        assemble(self.source, plan, self.base/'release')
        cancel = threading.Event()
        def event(value):
            if value['phase'] == 'Extracting':
                cancel.set()
        with self.assertRaises(Cancelled):
            extract_verified(self.base/'release/release.zip', self.base/'unpacked', operation=Operation(event, cancel))
        self.assertFalse((self.base/'unpacked').exists())
        self.assertFalse(list(self.base.glob('.releasecraft-extract-*')))

    def test_reviewed_required_exclusion_and_secret_mutation_stay_blocked(self):
        plan = analyze(self.source)
        policy = decide(plan, review_policy(plan), 'sample.csv', 'exclude', 'Intentional conflicting decision')
        self.assertEqual(analyze(self.source, policy)['status'], 'BLOCKED')
        self.put('other.json', '{}')
        plan = analyze(self.source)
        policy = decide(plan, review_policy(plan), 'other.json', 'include', 'Reviewed settings')
        self.put('other.json', json.dumps({'pass'+'word':'synthetic-only-value'}))
        result = analyze(self.source, policy)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertNotIn('other.json', [r['path'] for r in result['files'] if r['state']=='INCLUDE'])

    def test_mtime_does_not_choose_release_and_equal_length_edits_change_identity(self):
        before = analyze(self.source)
        path = self.source/'sample.csv'
        saved = path.stat()
        os.utime(path, ns=(saved.st_atime_ns, saved.st_mtime_ns+10_000_000))
        self.assertEqual(before, analyze(self.source))
        path.write_bytes(b'3,4\n')
        os.utime(path, ns=(saved.st_atime_ns, saved.st_mtime_ns))
        after = analyze(self.source)
        self.assertNotEqual(before['snapshot_sha256'], after['snapshot_sha256'])
        self.assertEqual(plan_diff(before, after)['content_changed'], ['sample.csv'])

    def test_worktree_git_pointer_is_private_and_never_opted_in(self):
        path = self.put('.git', 'gitdir: ../private-worktree-data\n')
        plan = analyze(self.source, {'include':['.git']})
        self.assertEqual(plan['status'], 'PLANNED')
        row = next(r for r in plan['files'] if r['path']=='.git')
        self.assertEqual((row['state'], row['reason']), ('EXCLUDE', 'private-repository-metadata'))
        with self.assertRaises(ReleaseError):
            decide(plan, review_policy(plan), '.git', 'include', 'Cannot publish local Git pointer')
        self.assertEqual(path.read_text(), 'gitdir: ../private-worktree-data\n')

    def test_citation_is_source_maintenance_without_secret_override(self):
        path = self.put('CITATION.cff', 'cff-version: 1.2.0\ntitle: Synthetic dataset\n')
        plan = analyze(self.source)
        self.assertEqual(plan['status'], 'PLANNED')
        row = next(r for r in plan['files'] if r['path']=='CITATION.cff')
        self.assertEqual(row['state'], 'INCLUDE')
        path.write_text('gh'+'p_'+'Q'*30, encoding='utf8')
        self.assertEqual(analyze(self.source, {'include':['CITATION.cff']})['status'], 'BLOCKED')

    def test_immediate_generated_json_context_reader_preserves_missing_input_gates(self):
        writer = 'import json\nassert open("sample.csv").read()\nwith open("result.json", "w") as target:\n    json.dump({"value":19}, target)\n'
        for call in ('open("result.json")', 'open(file="result.json",mode="r")'):
            self.put('main.py', writer + f'with {call} as stream:\n    assert json.load(stream)["value"] == 19\n')
            self.assertEqual(analyze(self.source)['status'], 'PLANNED')
        for reader in (
            'with open("missing.json") as stream:\n    json.load(stream)\n',
            'unknown_operation()\nwith open("result.json") as stream:\n    json.load(stream)\n',
            'with open("result.json") as stream, unknown_context():\n    json.load(stream)\n',
            'with open("result.json") as stream:\n    unknown_operation()\n    json.load(stream)\n',
        ):
            self.put('main.py', writer + reader)
            self.assertEqual(analyze(self.source)['status'], 'BLOCKED')
        self.put('main.py', 'with open("missing.json", "r+") as target:\n    target.write("{}")\nwith open("missing.json") as stream:\n    assert True\n')
        self.assertEqual(analyze(self.source)['status'], 'BLOCKED')


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Native Tk display required')
class ReviewDesktopTests(unittest.TestCase):
    def test_pending_decisions_survive_language_switch_export_and_reanalysis(self):
        self.check_review_persistence('config.json', b'{}')

    def test_binary_review_survives_gui_save_language_switch_and_reanalysis(self):
        self.check_review_persistence('screenshots/home.png', b'\x89PNG\x00public-screenshot')

    def check_review_persistence(self, reviewed_path, payload):
        import tkinter as tk
        from releasecraft.desktop import App
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base/'source 空间'
            source.mkdir()
            for name, data in {'LICENSE':'MIT License\nPermission is hereby granted\n', 'README.md':'# Fixture\n', 'main.py':'print("fixture")\n'}.items():
                (source/name).write_text(data, encoding='utf8')
            resource = source / reviewed_path
            resource.parent.mkdir(parents=True, exist_ok=True)
            resource.write_bytes(payload)
            root = tk.Tk()
            root.withdraw()
            app = App(root, source=str(source), state=base/'state')
            try:
                app.result = prepare(source, operation=Operation(state_directory=base/'state'), review_only=True)
                self.assertEqual(app.result['status'], 'BLOCKED')
                app.show_review()
                panel = app.review_window
                from tkinter import font as tkfont
                self.assertGreater(panel.table.column('state', 'minwidth'), tkfont.nametofont('TkDefaultFont').measure('UNRESOLVED'))
                key = next(k for k, row in panel.rows.items() if row['path']==reviewed_path)
                panel.table.selection_set(key)
                panel.reason.set('Reviewed public configuration')
                panel.apply('include')
                saved = canonical(panel.policy)
                for language in ('中文', 'English', '中文'):
                    app.language_choice.set(language)
                    app.change_language()
                    root.update()
                    self.assertEqual(canonical(panel.policy), saved)
                    self.assertIn(app.tr('review.pending'), panel.table.set(key, 'state'))
                path = base/'reviewed.json'
                with patch('releasecraft.review_ui.filedialog.asksaveasfilename', return_value=str(path)), patch('releasecraft.review_ui.messagebox.showinfo'):
                    panel.save()
                self.assertEqual(path.read_bytes(), saved)
                self.assertEqual(app.policy_path.get(), str(path))
                rerun = prepare(source, policy=json.loads(saved), operation=Operation(state_directory=base/'state'), review_only=True)
                self.assertEqual(rerun['status'], 'PLANNED', rerun.get('problems'))
                self.assertEqual(resource.read_bytes(), payload)
                published = prepare(source, policy=json.loads(saved), operation=Operation(state_directory=base/'state'))
                self.assertEqual(published['status'], 'CANDIDATE')
                with zipfile.ZipFile(Path(published['output']) / 'release.zip') as archive:
                    self.assertEqual(archive.read(reviewed_path), payload)
                with patch('releasecraft.review_ui.filedialog.asksaveasfilename', return_value=str(path)), patch('releasecraft.review_ui.messagebox.showerror') as rejected:
                    panel.save()
                    rejected.assert_called_once()
                self.assertEqual(path.read_bytes(), saved)
            finally:
                app.close()


if __name__ == '__main__':
    unittest.main()
