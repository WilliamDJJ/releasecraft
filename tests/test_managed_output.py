"""Synthetic owned-output, cancellation, mutation and scope boundary contracts."""
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile
from releasecraft.analyze import analyze
from releasecraft.build import assemble, verify_archive
from releasecraft.directory import Directory
from releasecraft.managed import prepare, owned_output, lease, MARKER
from releasecraft.operation import Operation, Cancelled
from releasecraft.safety import ReleaseError, digest


class ManagedOutputTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.source = self.base / 'project space 测试'
        self.source.mkdir()
        self.state = self.base / 'private'
        for name, text in {'LICENSE':'MIT License\nPermission is hereby granted\n', 'README.md':'# Sample\nRun python main.py\n', 'main.py':'import json\nassert json.load(open("data.json"))["value"] == 3\n', 'data.json':'{"value":3}\n'}.items():
            (self.source / name).write_text(text,encoding='utf8')
        self.original = {p.name:p.read_bytes() for p in self.source.iterdir()}

    def tearDown(self):
        self.temp.cleanup()

    def op(self, callback=None):
        return Operation(callback, state_directory=self.state)

    def run_prepare(self, **kwargs):
        return prepare(self.source, operation=kwargs.pop('operation', self.op()), **kwargs)

    def test_default_candidate_has_exact_files_and_private_audit(self):
        result = self.run_prepare()
        self.assertEqual(result['status'],'CANDIDATE')
        self.assertEqual(result['runtime_checks'],'not-run')
        self.assertEqual(result['payload_files'],len(self.original))
        output = Path(result['output'])
        self.assertEqual(result['archive_bytes'],(output/'release.zip').stat().st_size)
        self.assertEqual(output.parent,self.source/'releasecraft-output')
        self.assertTrue(Path(result['audit']).is_relative_to(self.state))
        self.assertEqual({p.name for p in output.iterdir()},{'release.zip','release.zip.sha256','CHECKS.json'})
        with zipfile.ZipFile(output/'release.zip') as z:
            self.assertEqual(set(z.namelist()),set(self.original)|{'RELEASE-MANIFEST.json'})
            for name,data in self.original.items():
                self.assertEqual(z.read(name),data)
        self.assertEqual({name:(self.source/name).read_bytes() for name in self.original},self.original)

    @unittest.skipUnless(os.name == 'nt', 'Windows short-path alias')
    def test_private_state_short_path_keeps_journal_and_repeat_identity(self):
        import ctypes
        from ctypes import wintypes

        self.state.mkdir()
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetShortPathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
        kernel.GetShortPathNameW.restype = wintypes.DWORD
        buffer = ctypes.create_unicode_buffer(32768)
        length = kernel.GetShortPathNameW(str(self.state), buffer, len(buffer))
        if not length:
            raise ctypes.WinError(ctypes.get_last_error())
        self.assertLess(length, len(buffer))
        alias = Path(buffer.value)
        if alias == self.state.resolve():
            self.skipTest('Filesystem supplies no distinct short-path alias')
        self.assertTrue(alias.samefile(self.state))
        first = prepare(self.source, operation=Operation(state_directory=alias))
        second = prepare(self.source, operation=Operation(state_directory=alias))
        self.assertEqual(first['status'], 'CANDIDATE')
        self.assertEqual(second['status'], 'CANDIDATE')
        self.assertEqual(first['archive_sha256'], second['archive_sha256'])
        self.assertNotEqual(first['output'], second['output'])
        self.assertTrue(Path(first['audit']).is_relative_to(alias))
        self.assertEqual({name:(self.source/name).read_bytes() for name in self.original}, self.original)

    def test_assembly_rejects_stage_outside_its_private_journal(self):
        from releasecraft.storage import Storage

        plan = analyze(self.source)
        self.assertEqual(plan['status'], 'PLANNED')
        with Storage(self.state) as storage:
            _, tree = storage.new_job()
            wrong = tree.path / 'unregistered-stage'
            with self.assertRaisesRegex(ReleaseError, 'Private stage must match'):
                assemble(self.source, plan, wrong, owned_tree=tree)
            self.assertFalse(wrong.exists())
            self.assertFalse((tree.path / 'stage').exists())

    def test_mutation_at_publication_boundary_rejects_candidate(self):
        def mutate(event):
            if event['phase'] == 'Publishing':
                (self.source/'data.json').write_text('{"value":99}',encoding='utf8')
        with self.assertRaises(ReleaseError):
            self.run_prepare(operation=self.op(mutate))
        self.assertFalse(list((self.source/'releasecraft-output').glob('release-*')))
        self.assertFalse(list((self.source/'releasecraft-output').glob('.pending-*')))

    def test_repeat_is_new_output_identical_archive_and_stable_plan(self):
        first=self.run_prepare(); second=self.run_prepare()
        self.assertNotEqual(first['output'],second['output'])
        self.assertEqual(first['archive_sha256'],second['archive_sha256'])
        a=json.loads((Path(first['audit'])/'plan.json').read_bytes())
        b=json.loads((Path(second['audit'])/'plan.json').read_bytes())
        self.assertEqual(a['plan_sha256'],b['plan_sha256'])
        self.assertNotIn('releasecraft-output/',json.dumps([r['path'] for r in b['files']]))

    def test_pending_payload_mutation_is_not_published_as_verified(self):
        def mutate(event):
            if event['phase'] == 'Publishing':
                pending = next((self.source/'releasecraft-output').glob('.pending-*'))
                (pending/'release.zip').write_bytes(b'changed after verification')
        with self.assertRaises((OSError, ReleaseError)):
            self.run_prepare(operation=self.op(mutate))
        self.assertFalse(list((self.source/'releasecraft-output').glob('release-*')))

    def test_pending_directory_replacement_is_rejected_and_retained(self):
        def replace(event):
            if event['phase'] == 'Publishing':
                pending = next((self.source/'releasecraft-output').glob('.pending-*'))
                pending.rename(pending.with_name('displaced-owned-output'))
                pending.mkdir()
                (pending/'keep.txt').write_text('user content')
        with self.assertRaises((OSError, ReleaseError)):
            self.run_prepare(operation=self.op(replace))
        self.assertFalse(list((self.source/'releasecraft-output').glob('release-*')))
        self.assertEqual(next((self.source/'releasecraft-output').glob('.pending-*/keep.txt')).read_text(),'user content')

    def test_cancel_retains_unexpected_pending_content(self):
        op=self.op()
        def mutate(event):
            if event['phase']=='Publishing':
                pending=next((self.source/'releasecraft-output').glob('.pending-*'))
                (pending/'keep.txt').write_text('keep')
                op.cancelled.set()
        op.callback=mutate
        result=self.run_prepare(operation=op)
        self.assertEqual(result['status'],'CANCELLED')
        self.assertEqual(next((self.source/'releasecraft-output').glob('.pending-*/keep.txt')).read_text(),'keep')
        self.assertEqual(json.loads((Path(result['audit'])/'cleanup.json').read_bytes())['status'],'RETAINED')

    def test_hardlinked_marker_and_lease_fail_closed(self):
        self.run_prepare()
        output=self.source/'releasecraft-output'
        for name in (MARKER,'.lease'):
            with self.subTest(name=name):
                hard=self.base/('hard-'+name)
                os.link(output/name,hard)
                with self.assertRaises((OSError,ReleaseError)):self.run_prepare()
                hard.unlink()

    def test_core_default_scan_recognizes_registered_output(self):
        self.run_prepare()
        with patch('releasecraft.managed.state_directory',return_value=self.state):
            plan=analyze(self.source)
        self.assertEqual(plan['status'],'PLANNED')
        self.assertEqual(next(r['reason'] for r in plan['files'] if r['path']=='releasecraft-output'),'owned-releasecraft-output')

    def test_preexisting_unowned_directory_is_not_adopted(self):
        output=self.source/'releasecraft-output';output.mkdir()
        (output/'keep.txt').write_text('keep')
        with self.assertRaises((OSError,ReleaseError)):
            self.run_prepare()
        self.assertEqual((output/'keep.txt').read_text(),'keep')
        self.assertFalse((output/MARKER).exists())
        self.assertEqual(analyze(self.source,operation=self.op())['status'],'BLOCKED')

    def test_forged_or_copied_marker_does_not_authorize_pruning(self):
        original=self.run_prepare()
        other=self.base/'other';other.mkdir()
        for name,data in self.original.items():(other/name).write_bytes(data)
        output=other/'releasecraft-output';output.mkdir()
        (output/MARKER).write_bytes((Path(original['output']).parent/MARKER).read_bytes())
        self.assertFalse(owned_output(output,other,self.state))
        self.assertEqual(analyze(other,operation=self.op())['status'],'BLOCKED')

    def test_missing_registration_never_trusts_marker_alone(self):
        self.run_prepare()
        for path in (self.state/'owners').iterdir():path.unlink()
        self.assertFalse(owned_output(self.source/'releasecraft-output',self.source,self.state))
        with self.assertRaises(ReleaseError):self.run_prepare()

    def test_external_output_does_not_write_project(self):
        external=self.base/'external';external.mkdir()
        result=self.run_prepare(output=external/'releasecraft-output')
        self.assertEqual(result['status'],'CANDIDATE')
        self.assertFalse((self.source/'releasecraft-output').exists())
        self.assertEqual({p.name:p.read_bytes() for p in self.source.iterdir()},self.original)

    def test_nested_arbitrary_output_and_private_state_in_source_rejected(self):
        with self.assertRaises(ReleaseError):self.run_prepare(output=self.source/'nested/releasecraft-output')
        with self.assertRaises(ReleaseError):prepare(self.source,operation=Operation(state_directory=self.source/'audit'))

    def test_cancel_before_scan_does_not_create_project_output(self):
        op=self.op();op.cancelled.set()
        with self.assertRaises(Cancelled):self.run_prepare(operation=op)
        self.assertFalse((self.source/'releasecraft-output').exists())

    def test_cancel_scan_copy_and_publish_never_leaves_public_candidate(self):
        for phase in ('Scanning','Copying','Publishing'):
            with self.subTest(phase=phase):
                op=self.op()
                def callback(event):
                    if event['phase']==phase:op.cancelled.set()
                op.callback=callback
                result=self.run_prepare(operation=op)
                self.assertEqual(result['status'],'CANCELLED')
                self.assertEqual(list((self.source/'releasecraft-output').glob('release-*')),[])
                self.assertEqual(list((self.source/'releasecraft-output').glob('.pending-*')),[])
                self.assertEqual(json.loads((Path(result['audit'])/'status.json').read_bytes())['status'],'CANCELLED')
        self.assertEqual(self.run_prepare()['status'],'CANDIDATE')

    def test_progress_is_measured_and_does_not_change_plan_identity(self):
        events=[]
        first=analyze(self.source,operation=self.op(events.append))
        second=analyze(self.source)
        self.assertEqual(first['plan_sha256'],second['plan_sha256'])
        scanning=[e for e in events if e['phase']=='Scanning']
        self.assertTrue(scanning)
        self.assertTrue(all(e['total_files'] is None for e in scanning))
        self.assertTrue(all(e['bytes_read']<=sum(map(len,self.original.values())) for e in scanning))
        self.assertTrue(all(a['elapsed_seconds']<=b['elapsed_seconds'] for a,b in zip(events,events[1:])))

    def test_source_mutation_during_copy_fails_without_public_archive(self):
        changed=False
        def callback(event):
            nonlocal changed
            if event['phase']=='Copying' and not changed:
                (self.source/'data.json').write_text('{"value":9}')
                changed=True
        with self.assertRaises(ReleaseError):self.run_prepare(operation=self.op(callback))
        self.assertEqual(list((self.source/'releasecraft-output').glob('release-*')),[])

    def test_required_exclusion_and_secret_override_remain_blocked(self):
        result=self.run_prepare(policy={'exclude':['data.json']})
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('dependency-not-included',{r['code'] for r in result['problems']})
        (self.source/'data.json').write_text(json.dumps({'value':3,'token':'ghp_'+'Q'*30}))
        result=self.run_prepare(policy={'include':['data.json']})
        self.assertEqual(result['status'],'BLOCKED')
        self.assertIn('sensitive-content',{r['code'] for r in result['problems']})
        self.assertNotIn('ghp_'+'Q'*30,json.dumps(result))

    def test_busy_lease_refuses_second_job_and_recovers_after_release(self):
        self.run_prepare()
        with Directory(self.source/'releasecraft-output') as directory, lease(directory):
            with self.assertRaises((OSError,ReleaseError)):self.run_prepare()
        self.assertEqual(self.run_prepare()['status'],'CANDIDATE')

    def test_exclusive_files_and_directory_commit_never_overwrite(self):
        with Directory(self.base) as directory:
            directory.write_new('keep',b'original')
            with self.assertRaises(FileExistsError):directory.write_new('keep',b'changed')
            directory.mkdir('pending');directory.mkdir('existing')
            with self.assertRaises(OSError):directory.commit_directory('pending','existing')
            self.assertEqual((self.base/'keep').read_bytes(),b'original')

    @unittest.skipUnless(os.name=='nt','Windows junction boundary')
    def test_output_junction_and_ancestor_junction_rejected(self):
        import subprocess
        target=self.base/'target';target.mkdir()
        for path in [self.source/'releasecraft-output',self.base/'external-link']:
            result=subprocess.run(['cmd','/d','/c','mklink','/J',str(path),str(target)],capture_output=True,timeout=10)
            if result.returncode:self.skipTest('Junction creation unavailable')
            output=path if path.name=='releasecraft-output' else path/'releasecraft-output'
            with self.assertRaises((OSError,ReleaseError)):self.run_prepare(output=output)
        self.assertEqual(list(target.iterdir()),[])

    @unittest.skipUnless(os.name=='posix','POSIX directory symlink boundary')
    def test_output_symlink_and_ancestor_symlink_rejected(self):
        target=self.base/'target';target.mkdir()
        (self.source/'releasecraft-output').symlink_to(target,target_is_directory=True)
        with self.assertRaises((OSError,ReleaseError)):self.run_prepare()
        self.assertEqual(list(target.iterdir()),[])


if __name__=='__main__':unittest.main()
