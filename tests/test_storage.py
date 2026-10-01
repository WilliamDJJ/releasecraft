"""Owned staging, bounded audits, recovery and explicit retention boundaries."""
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from releasecraft.managed import prepare
from releasecraft.operation import Operation
from releasecraft.safety import ReleaseError, digest
from releasecraft.storage import Storage, StorageBlocked, clean_storage, export_audit, storage_status


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / 'source space 中文'
        self.source.mkdir()
        (self.source / 'LICENSE').write_text('MIT License\nPermission is hereby granted\n')
        (self.source / 'README.md').write_text('# Synthetic project\nRun python main.py\n')
        (self.source / 'main.py').write_text('import json\nassert json.load(open("values.json"))["n"] == 3\n')
        (self.source / 'values.json').write_text('{"n":3}\n')
        self.original = {p.name:p.read_bytes() for p in self.source.iterdir()}
        self.state = self.root / 'private'

    def tearDown(self):
        self.temp.cleanup()

    def run_prepare(self, callback=None, policy=None):
        return prepare(self.source, policy=policy, operation=Operation(callback, state_directory=self.state))

    def test_success_cleans_stage_but_preserves_audit_and_source(self):
        result = self.run_prepare()
        self.assertEqual(result['status'], 'CANDIDATE')
        self.assertNotIn('storage_warning', result)
        self.assertFalse((Path(result['audit']) / 'stage').exists())
        self.assertTrue((Path(result['audit']) / 'plan.json').is_file())
        self.assertEqual(json.loads((Path(result['audit']) / 'status.json').read_bytes())['status'], 'CANDIDATE')
        self.assertEqual({n:(self.source/n).read_bytes() for n in self.original}, self.original)

    def test_cancel_after_assembly_cleans_exact_stage(self):
        op = Operation(state_directory=self.state)
        def cancel(event):
            if event['phase'] == 'Verifying':
                op.cancelled.set()
        op.callback = cancel
        result = prepare(self.source, operation=op)
        self.assertEqual(result['status'], 'CANCELLED')
        self.assertFalse((Path(result['audit']) / 'stage').exists())
        self.assertFalse(list((self.source / 'releasecraft-output').glob('release-*')))

    def test_copy_failure_cleans_journaled_partial_stage(self):
        def mutate(event):
            if event['phase'] == 'Copying' and event['current'] == 'values.json':
                (self.source / 'values.json').write_text('{"n":4}')
        with self.assertRaises(ReleaseError):
            self.run_prepare(mutate)
        status = storage_status(self.state)
        self.assertEqual(status['jobs'][0]['status'], 'FAILED')
        self.assertEqual(status['jobs'][0]['cleanup'], 'CLEAN')
        self.assertFalse(list((self.state / 'jobs').glob('*/stage')))

    def test_repeated_success_block_and_compact_count_are_bounded(self):
        with patch('releasecraft.storage.AUDIT_COUNT', 2), patch('releasecraft.storage.HISTORY_COUNT', 4):
            first = self.run_prepare()
            for i in range(6):
                result = self.run_prepare(policy={'exclude':['values.json']} if i % 2 else None)
                self.assertEqual(result['status'], 'BLOCKED' if i % 2 else 'CANDIDATE')
                if result['status'] == 'CANDIDATE':
                    self.assertEqual(first['archive_sha256'], result['archive_sha256'])
            status = storage_status(self.state)
            self.assertEqual(len(status['jobs']), 4)
            self.assertEqual(sum(r['retained'] for r in status['jobs']), 2)
            self.assertEqual(len(list((self.state / 'jobs').iterdir())), 2)
            self.assertEqual(len(list((self.state / 'journals').iterdir())), 2)

    def test_aggregate_audit_bytes_expire_old_details(self):
        one = self.run_prepare()
        size = storage_status(self.state)['jobs'][0]['audit_bytes']
        with patch('releasecraft.storage.TOTAL_AUDITS', size + 1000):
            self.run_prepare()
            jobs = storage_status(self.state)['jobs']
            self.assertEqual(sum(r['retained'] for r in jobs), 1)
            self.assertFalse(Path(one['audit']).exists())

    def test_oversized_plan_blocks_before_stage(self):
        with patch('releasecraft.managed.AUDIT_BYTES', 256):
            result = self.run_prepare()
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(result['code'], 'STORAGE_BLOCKED')
        self.assertFalse(list((self.state / 'jobs').glob('*/stage')))

    def test_capacity_refusal_does_not_create_project_output(self):
        with patch('releasecraft.storage.STATE_BYTES', 1024):
            result = self.run_prepare()
        self.assertEqual(result['code'], 'STORAGE_BLOCKED')
        self.assertFalse((self.source / 'releasecraft-output').exists())

    def test_small_project_reservation_is_below_maximum(self):
        seen=[]
        def inspect(event):
            if event['phase']=='Copying':
                rows=json.loads((self.state/'storage-index.json').read_bytes())['jobs']
                seen.append(rows[-1]['reservation_bytes'])
        self.assertEqual(self.run_prepare(inspect)['status'], 'CANDIDATE')
        self.assertTrue(seen)
        self.assertLess(max(seen), 1024 * 1024)

    def test_unknown_content_is_retained_and_measured(self):
        def add(event):
            if event['phase']=='Completing staging':
                stage=next((self.state/'jobs').glob('*/stage'))
                (stage/'keep.txt').write_bytes(b'not registered')
        result=self.run_prepare(add)
        self.assertEqual(result['status'],'CANDIDATE')
        self.assertEqual(result['storage_warning'],'private-staging-retained')
        keep=Path(result['audit'])/'stage/keep.txt'
        clean_storage(self.state, clear_audits=True)
        self.assertEqual(keep.read_bytes(),b'not registered')
        self.assertEqual(storage_status(self.state)['jobs'][0]['cleanup'],'RETAINED')

    def test_replaced_stage_directory_is_retained(self):
        def replace(event):
            if event['phase']=='Completing staging':
                stage=next((self.state/'jobs').glob('*/stage'))
                stage.rename(stage.with_name('displaced-stage'))
                stage.mkdir()
                (stage/'keep').write_text('user data')
        with self.assertRaises((ReleaseError, OSError)):
            self.run_prepare(replace)
        self.assertEqual(next((self.state/'jobs').glob('*/stage/keep')).read_text(),'user data')

    def test_added_hardlink_prevents_cleanup(self):
        def link(event):
            if event['phase']=='Completing staging':
                archive=next((self.state/'jobs').glob('*/stage/release.zip'))
                os.link(archive,self.root/'hard-link.zip')
        result=self.run_prepare(link)
        self.assertEqual(result['storage_warning'],'private-staging-retained')
        self.assertTrue((Path(result['audit'])/'stage/release.zip').exists())

    def test_active_job_cannot_be_cleaned_or_admitted_twice(self):
        with Storage(self.state) as store:
            row, tree = store.new_job()
            tree.write('plan.json',b'{}')
            with self.assertRaises((OSError, ReleaseError)):
                clean_storage(self.state,True)
            self.assertTrue(tree.path.exists())
            with self.assertRaises((OSError, ReleaseError)):
                with Storage(self.state):
                    pass

    def test_crash_recovery_cleans_only_finalized_journal_entries(self):
        with Storage(self.state) as store:
            row, tree=store.new_job()
            tree.write('stage/source/known.txt',b'known')
            identifier=row['id']
        with Storage(self.state) as store:
            store.maintain()
            self.assertEqual(store.index[0]['status'],'INTERRUPTED')
            self.assertFalse((self.state/'jobs'/identifier/'stage').exists())

    def test_crash_before_journal_finalization_retains_unknown(self):
        with Storage(self.state) as store:
            row,tree=store.new_job()
            tree.mkdir('stage')
            (tree.path/'stage/unfinished').write_bytes(b'unknown')
        with Storage(self.state) as store:
            store.maintain()
            self.assertEqual(store.index[0]['cleanup'],'RETAINED')
            self.assertTrue((tree.path/'stage/unfinished').exists())

    def test_write_budget_checked_before_content_write(self):
        with Storage(self.state) as store:
            row,tree=store.new_job()
            tree.limit=3
            with self.assertRaises(StorageBlocked):
                tree.write('stage/too-big',b'four')
            self.assertEqual((tree.path/'stage/too-big').read_bytes(),b'')
            tree.clean('stage')

    def test_export_is_exact_and_never_overwrites(self):
        result=self.run_prepare()
        identifier=Path(result['audit']).name
        dest=self.root/'audit.zip'
        export_audit(self.state,identifier,dest)
        with zipfile.ZipFile(dest) as archive:
            self.assertEqual(set(archive.namelist()),{'plan.json','status.json'})
            for name in archive.namelist():
                self.assertEqual(archive.read(name),(Path(result['audit'])/name).read_bytes())
        old=digest(dest.read_bytes())
        with self.assertRaises(FileExistsError):export_audit(self.state,identifier,dest)
        self.assertEqual(digest(dest.read_bytes()),old)

    def test_clear_audits_keeps_public_package_and_compact_status(self):
        result=self.run_prepare()
        public=Path(result['output'])/'release.zip'
        sha=digest(public.read_bytes())
        clean_storage(self.state,True)
        self.assertFalse(Path(result['audit']).exists())
        self.assertEqual(digest(public.read_bytes()),sha)
        self.assertEqual(storage_status(self.state)['jobs'][0]['status'],'CANDIDATE')

    def test_unregistered_legacy_job_is_not_adopted(self):
        with Storage(self.state):pass
        legacy=self.state/'jobs/legacy'
        legacy.mkdir();(legacy/'stage.zip').write_bytes(b'old unique work')
        clean_storage(self.state,True)
        self.assertEqual((legacy/'stage.zip').read_bytes(),b'old unique work')

    def test_owner_limit_does_not_forget_registrations(self):
        self.run_prepare()
        with patch('releasecraft.managed.OWNER_COUNT',0):
            other=self.root/'other';other.mkdir()
            for name,data in self.original.items():(other/name).write_bytes(data)
            result=prepare(other,operation=Operation(state_directory=self.state))
        self.assertEqual(result['code'],'STORAGE_BLOCKED')
        self.assertFalse((other/'releasecraft-output').exists())
        self.assertEqual(len(list((self.state/'owners').iterdir())),1)

    def test_storage_enumeration_is_bounded(self):
        self.run_prepare()
        with patch('releasecraft.storage.ENTRY_COUNT',1):
            self.assertEqual(self.run_prepare()['code'],'STORAGE_BLOCKED')

    def test_replaced_index_is_never_overwritten_by_maintenance(self):
        with Storage(self.state) as store:
            store.save()
            path=self.state/'storage-index.json'
            path.write_bytes(b'changed private record')
            with self.assertRaises((OSError,ReleaseError)):
                store.maintain()
            self.assertEqual(path.read_bytes(),b'changed private record')

    @unittest.skipUnless(os.name=='posix','POSIX broken-link retention boundary')
    def test_broken_index_link_is_not_adopted(self):
        self.state.mkdir()
        index=self.state/'storage-index.json'
        index.symlink_to(self.root/'missing-private-record')
        with self.assertRaises((OSError,ReleaseError)):
            with Storage(self.state) as store:
                store.maintain()
        self.assertTrue(index.is_symlink())

    def test_modified_pending_bytes_are_retained(self):
        def change(event):
            if event['phase']=='Publishing':
                archive=next((self.source/'releasecraft-output').glob('.pending-*/release.zip'))
                archive.write_bytes(b'changed user content')
        with self.assertRaises((OSError,ReleaseError)):
            self.run_prepare(change)
        self.assertEqual(next((self.source/'releasecraft-output').glob('.pending-*/release.zip')).read_bytes(),b'changed user content')

    @unittest.skipUnless(os.name=='nt','NTFS junction retention boundary')
    def test_unknown_junction_does_not_authorize_target_cleanup(self):
        import subprocess
        outside=self.root/'target';outside.mkdir()
        (outside/'keep').write_bytes(b'keep')
        result=self.run_prepare()
        job=Path(result['audit'])
        created=subprocess.run(['cmd','/d','/c','mklink','/J',str(job/'foreign'),str(outside)],capture_output=True,timeout=10)
        if created.returncode:self.skipTest('Junction creation unavailable')
        with self.assertRaises((OSError,ReleaseError)):
            clean_storage(self.state,True)
        self.assertEqual((outside/'keep').read_bytes(),b'keep')

    def test_existing_unknown_capacity_can_be_reported_without_deletion(self):
        self.run_prepare()
        (self.state/'unknown').write_bytes(b'x'*1024)
        with patch('releasecraft.storage.STATE_BYTES',100):
            status=storage_status(self.state)
            self.assertEqual(status['status'],'AVAILABLE')
            self.assertGreater(status['bytes'],status['limit_bytes'])
            self.assertEqual(self.run_prepare()['code'],'STORAGE_BLOCKED')
        self.assertEqual((self.state/'unknown').stat().st_size,1024)


if __name__=='__main__':unittest.main()
