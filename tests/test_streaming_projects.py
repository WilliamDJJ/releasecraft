"""Stream boundaries, real payload hashes and independent resource expectations."""
import hashlib
import io
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

from releasecraft.analyze import analyze
from releasecraft.archive import frozen_archive
from releasecraft.build import assemble, extract_verified, verify_archive
from releasecraft.managed import prepare
from releasecraft.operation import Operation, Cancelled
from releasecraft.policy import load_policy
from releasecraft.safety import ReleaseError, findings
from releasecraft.streaming import ContentScanner, PARSE_BYTES, SCAN_WINDOW, chunks, snapshot, SpaceError


class StreamingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'source space 数据'
        self.root.mkdir()
        self.put('LICENSE', b'MIT License\nPermission is hereby granted\n')
        self.put('README.md', b'# Dataset reader\n')
        self.put('main.py', b'with open("records.csv", "rb") as f:\n    assert f.read(3) == b"1,2"\n')
        self.put('records.csv', b'1,2,3\n')

    def put(self, rel, data):
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_no_default_file_or_project_byte_ceiling(self):
        policy = load_policy()
        self.assertIsNone(policy['max_file_bytes'])
        self.assertIsNone(policy['max_scan_bytes'])
        self.assertEqual(load_policy(value={'max_file_bytes': 5 * 1024**3})['max_file_bytes'], 5 * 1024**3)

    def test_optional_byte_budget_is_honest_block(self):
        self.put('records.csv', b'1,2,3\n' * 1000)
        plan = analyze(self.root, {'max_scan_bytes': 1024})
        self.assertEqual(plan['status'], 'BLOCKED')
        self.assertEqual(plan['scan']['stop_reason'], 'scan-byte-limit')
        with self.assertRaises(ReleaseError):
            assemble(self.root, plan, self.base / 'out')

    def test_chunks_never_request_whole_payload(self):
        class Checked(io.BytesIO):
            def read(self, size=-1):
                self.assertion(size)
                return super().read(size)
        data = b'x' * (1024 * 1024 + 7)
        stream = Checked(data)
        stream.assertion = lambda size: self.assertTrue(0 < size <= 1024 * 1024)
        self.assertEqual(hashlib.sha256(b''.join(chunks(stream, len(data)))).digest(), hashlib.sha256(data).digest())
        with self.assertRaises(ReleaseError):
            list(chunks(io.BytesIO(b'grown'), 3))
        with self.assertRaises(ReleaseError):
            list(chunks(io.BytesIO(b'shrank'), 20))

    def test_streamed_resource_preserves_full_hash_and_required_membership(self):
        data = b'1,2,3\n' * 40000
        path = self.put('records.csv', data)
        # Force opaque streaming with a small parser threshold; public behavior
        # is also exercised with actual >256 MiB files in acceptance.
        with patch('releasecraft.streaming.PARSE_BYTES', 1024), patch('releasecraft.analyze.PARSE_BYTES', 1024):
            plan = analyze(self.root)
            self.assertEqual(plan['status'], 'PLANNED')
            row = next(r for r in plan['files'] if r['path'] == 'records.csv')
            self.assertEqual((row['size'], row['sha256']), (len(data), hashlib.sha256(data).hexdigest()))
            self.assertEqual(row['state'], 'INCLUDE')
            first = assemble(self.root, plan, self.base / 'first')
            second = assemble(self.root, plan, self.base / 'second')
            self.assertEqual(first['archive_sha256'], second['archive_sha256'])
        extract_verified(self.base / 'first/release.zip', self.base / 'extracted')
        self.assertEqual((self.base / 'extracted/records.csv').read_bytes(), data)
        self.assertEqual(path.read_bytes(), data)

    def test_secrets_cross_every_window_boundary(self):
        fake = ('gh' + 'p_' + 'Q' * 30).encode()
        escaped_json = b'{"pass\\u0077ord":"q"}'
        for value in (fake, b'pass' + b'word = "synthetic-value-123"', escaped_json):
            for split in range(1, min(len(value), 20)):
                scanner = ContentScanner(PARSE_BYTES + 1)
                payload = b'\x00' * (SCAN_WINDOW - split) + value + b'\n' + b'\x00' * SCAN_WINDOW
                for start in range(0, len(payload), 8191):
                    scanner.feed(payload[start:start + 8191])
                result = scanner.finish()
                self.assertTrue(result, (value[:4], split))
                self.assertNotIn(value.decode(), json.dumps(result))

    def test_long_ambiguous_secret_context_blocks_instead_of_discarding(self):
        scanner = ContentScanner(PARSE_BYTES + 1)
        scanner.feed(b'password = "' + b'x' * (SCAN_WINDOW * 3) + b'"')
        self.assertTrue(scanner.finish())

    def test_multiline_sensitive_syntax_cannot_fall_out_of_stream_windows(self):
        cases = [
            b'{"password":' + b'\n' * (SCAN_WINDOW * 2) + b'"synthetic-secret-123"}',
            b'{"pass\\u0077ord"' + b'\r\n' * SCAN_WINDOW + b':"q"}',
            b'password' + b'\t\n' * SCAN_WINDOW + b'= "synthetic-secret-123"',
            b'{"db_password":' + b' \r\n' * SCAN_WINDOW + b'"q"}',
            b'{"password":' + '\u2003\n'.encode('utf8') * SCAN_WINDOW + b'"synthetic-secret-123"}',
            b'{"access_token":"' + b'x' * (SCAN_WINDOW * 2) + b'"}',
        ]
        for index, payload in enumerate(cases):
            with self.subTest(case=index):
                self.assertTrue(findings(payload))
                for split in (1, 17, 4095):
                    scanner = ContentScanner(PARSE_BYTES + 1)
                    data = b'\x00' * (SCAN_WINDOW - split) + payload + b'\n'
                    for offset in range(0, len(data), 8191):
                        scanner.feed(data[offset:offset + 8191])
                        self.assertLess(len(scanner.buffer), SCAN_WINDOW * 2)
                    result = scanner.finish()
                    self.assertTrue(result, (index, split))
                    self.assertNotIn('synthetic-secret-123', json.dumps(result))

    def test_large_completed_placeholder_does_not_need_unbounded_context(self):
        for data in (b'{"password":"${LOCAL_VALUE}"}\n', b'{"password":null}\n', b'{"public":' + b'\n' * (SCAN_WINDOW * 2) + b'"value"}\n'):
            scanner = ContentScanner(PARSE_BYTES + 1)
            for offset in range(0, len(data), 8191):
                scanner.feed(data[offset:offset + 8191])
            self.assertEqual(scanner.finish(), [])

    def test_real_large_multiline_credential_blocks_plan_build_verify_extract(self):
        from releasecraft.build import MANIFEST
        from releasecraft.safety import canonical

        name = 'resource.dat'
        path = self.put(name, b'public input')
        good = analyze(self.root, {'resources': [name]})
        self.assertEqual(good['status'], 'PLANNED')
        assemble(self.root, good, self.base / 'clean')
        prefix = b'{"password":' + b'\n' * (SCAN_WINDOW * 2) + b'"synthetic-secret-123"}\n'
        payload = prefix + b'\n' * (PARSE_BYTES + 1 - len(prefix))
        self.assertTrue(findings(payload))
        path.write_bytes(payload)
        for policy in ({'resources': [name]}, {'include': [name]}):
            with self.subTest(policy=policy):
                plan = analyze(self.root, policy)
                self.assertEqual(plan['status'], 'BLOCKED')
                row = next(r for r in plan['files'] if r['path'] == name)
                self.assertEqual(row['reason'], 'sensitive-content')
                self.assertNotIn('synthetic-secret-123', json.dumps(plan))
                with self.assertRaises(ReleaseError):
                    assemble(self.root, plan, self.base / 'unsafe')
        forged = self.base / 'supplied.zip'
        with zipfile.ZipFile(self.base / 'clean/release.zip') as src, zipfile.ZipFile(forged, 'w') as dst:
            manifest = json.loads(src.read(MANIFEST))
            row = next(r for r in manifest['files'] if r['path'] == name)
            row.update(size=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            for info in src.infolist():
                data = payload if info.filename == name else canonical(manifest) if info.filename == MANIFEST else src.read(info)
                dst.writestr(info, data)
        report = verify_archive(forged)
        self.assertEqual(report['status'], 'FAILED')
        self.assertIn('sensitive-content', [r['code'] for r in report['errors']])
        self.assertNotIn('synthetic-secret-123', json.dumps(report))
        with self.assertRaises(ReleaseError):
            extract_verified(forged, self.base / 'unpacked')
        self.assertFalse((self.base / 'unpacked').exists())

    def test_uncached_content_mutation_detected(self):
        path = self.root / 'records.csv'
        item = snapshot(self.root, 'records.csv', path.stat().st_size, cache=False)
        path.write_bytes(b'9,9,9\n')
        with self.assertRaises(ReleaseError):
            item.content()

    def test_cancellation_is_checked_inside_single_file(self):
        cancel = threading.Event()
        events = []
        def callback(event):
            events.append(event)
            if event['bytes_read'] > 0:
                cancel.set()
        op = Operation(callback, cancel)
        with self.assertRaises(Cancelled):
            list(chunks(io.BytesIO(b'x' * (2 * 1024 * 1024)), 2 * 1024 * 1024, op))
        self.assertEqual(len(events), 2)

    def test_disk_failure_prevents_staging(self):
        plan = analyze(self.root)
        with patch('releasecraft.streaming.shutil.disk_usage', return_value=type('Disk', (), {'free': 0})()):
            with self.assertRaises(SpaceError):
                assemble(self.root, plan, self.base / 'out')
        self.assertFalse((self.base / 'out').exists())
        self.assertFalse(list(self.base.glob('.releasecraft-stage-*')))

    def test_zip64_metadata_path_and_frozen_archive(self):
        plan = analyze(self.root)
        with patch.object(zipfile, 'ZIP64_LIMIT', 100):
            assemble(self.root, plan, self.base / 'out')
        archive = self.base / 'out/release.zip'
        self.assertIn(b'PK\x06\x06', archive.read_bytes())
        with frozen_archive(archive.read_bytes()) as frozen:
            archive.write_bytes(b'changed original')
            self.assertEqual(verify_archive(frozen)['status'], 'CANDIDATE')
            extract_verified(frozen, self.base / 'exact')
        self.assertEqual((self.base / 'exact/records.csv').read_bytes(), b'1,2,3\n')

    def test_large_opaque_managed_output_uses_streams(self):
        self.put('records.csv', b'1,2,3\n' * 60000)
        op = Operation(state_directory=self.base / 'state')
        with patch('releasecraft.storage.STAGE_BYTES', None), patch('releasecraft.storage.STATE_BYTES', None):
            result = prepare(self.root, operation=op)
        self.assertEqual(result['status'], 'CANDIDATE')
        self.assertNotIn('storage_warning', result)
        self.assertEqual(verify_archive(Path(result['output']) / 'release.zip')['status'], 'CANDIDATE')
        self.assertFalse((Path(result['audit']) / 'stage').exists())


if __name__ == '__main__':
    unittest.main()
