"""Independent release expectations for agent-authored project workspaces."""
import json
from pathlib import Path
import tempfile
import unittest

from releasecraft.analyze import analyze, plan_diff
from releasecraft.build import assemble, verify_cached
from releasecraft.managed import prepare
from releasecraft.operation import Operation
from releasecraft.review import decide, review_policy
from releasecraft.safety import ReleaseError, canonical


class AgentHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / 'agent project'
        self.root.mkdir()
        self.put('LICENSE', 'MIT License\nPermission is hereby granted\n')
        self.put('README.md', '# Example\nRun node main.js\n')
        self.put('main.js', 'console.log("hello")\n')
        self.put('package.json', '{"name":"agent-fixture","version":"1.0.0","main":"main.js"}')

    def put(self, path, content):
        dest = self.root / path
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content.encode() if isinstance(content, str) else content)
        return dest

    def states(self, plan):
        return {row['path']: (row['state'], row['reason']) for row in plan['files']}

    def playwright(self):
        self.put('package.json', '{"name":"fixture","devDependencies":{"@playwright/test":"1.0"}}')
        self.put('playwright.config.ts', 'export default { testDir: "tests" };\n')
        self.put('tests/page.spec.ts', 'export const sample = 1;\n')

    def test_shared_instructions_and_config_preserved_without_executing(self):
        expected = {'AGENTS.md', 'CLAUDE.md', '.codex/config.toml', '.claude/settings.json', '.cursor/rules/style.mdc'}
        for name, text in {
            'AGENTS.md': '# Build instructions\n', 'CLAUDE.md': '# Shared instructions\n',
            '.codex/config.toml': 'approval_policy = "on-request"\n',
            '.claude/settings.json': '{"permissions":{"allow":[]}}',
            '.cursor/rules/style.mdc': 'Use explicit names.\n',
        }.items():
            self.put(name, text)
        plan = analyze(self.root)
        self.assertEqual(plan['status'], 'PLANNED')
        selected = {r['path'] for r in plan['files'] if r['state'] == 'INCLUDE'}
        self.assertTrue(expected <= selected)

    def test_private_auth_state_cannot_be_opted_in(self):
        private = {'.claude/settings.local.json', '.codex/auth.json', '.codex/sessions/session.json', 'playwright/.auth/browser.json'}
        for name in private:
            self.put(name, '{}')
        plan = analyze(self.root, {'include': ['**', '*']})
        self.assertEqual(plan['status'], 'PLANNED')
        for name in private:
            self.assertEqual(self.states(plan)[name], ('EXCLUDE', 'private-agent-or-auth-state'))
            with self.assertRaises(ReleaseError):
                decide(plan, review_policy(plan), name, 'include', 'attempt')

    def test_shared_configuration_credentials_are_not_overrideable(self):
        for key in ('NPM_TOKEN', 'AUTH_TOKEN', 'db-password', 'api_key'):
            with self.subTest(key=key):
                self.put('.claude/settings.json', json.dumps({'env': {key: 'synthetic-test-value'}}))
                plan = analyze(self.root, {'include': ['.claude/settings.json']})
                self.assertEqual(plan['status'], 'BLOCKED')
                self.assertNotEqual(self.states(plan)['.claude/settings.json'][0], 'INCLUDE')
                with self.assertRaises(ReleaseError):
                    decide(plan, review_policy(plan), '.claude/settings.json', 'include', 'cannot approve secrets')

    def test_context_keeps_baseline_screenshot_and_auth_setup_source(self):
        self.playwright()
        self.put('tests/page.spec.ts-snapshots/home.png', b'\x89PNG\x00fixture')
        self.put('tests/auth.setup.ts', 'export const setup = true;\n')
        plan = analyze(self.root)
        self.assertEqual(plan['status'], 'PLANNED')
        self.assertEqual(self.states(plan)['tests/page.spec.ts-snapshots/home.png'], ('INCLUDE', 'playwright-baseline-input'))
        self.assertEqual(self.states(plan)['tests/auth.setup.ts'][0], 'INCLUDE')

    def test_report_names_without_context_are_not_auto_dropped(self):
        for name in ('reports/science.csv', 'screenshots/figure.png', 'dist/data.bin', '.yarn/cache/dependency.zip'):
            self.put(name, b'\x00fixture')
        plan = analyze(self.root)
        self.assertEqual(plan['status'], 'BLOCKED')
        for name in ('reports/science.csv', 'screenshots/figure.png', 'dist/data.bin', '.yarn/cache/dependency.zip'):
            self.assertEqual(self.states(plan)[name][0], 'UNRESOLVED')

    def test_generated_test_outputs_need_explicit_review(self):
        self.playwright()
        self.put('test-results/run/trace.zip', b'opaque')
        plan = analyze(self.root)
        self.assertEqual(self.states(plan)['test-results/run/trace.zip'], ('UNRESOLVED', 'generated-test-output-review'))
        policy = decide(plan, review_policy(plan), 'test-results/run/trace.zip', 'exclude', 'Generated test trace, not a baseline')
        reviewed = analyze(self.root, policy)
        self.assertEqual(reviewed['status'], 'PLANNED')
        self.assertEqual(self.states(reviewed)['test-results/run/trace.zip'][0], 'EXCLUDE')
        self.assertEqual((self.root / 'test-results/run/trace.zip').read_bytes(), b'opaque')

    def test_required_log_fixture_overrides_transient_default_not_explicit_exclude(self):
        self.put('reader.py', 'open("tests/fixture.log").read()\n')
        self.put('tests/fixture.log', 'bounded fixture\n')
        plan = analyze(self.root)
        self.assertEqual(plan['status'], 'PLANNED')
        self.assertEqual(self.states(plan)['tests/fixture.log'][0], 'INCLUDE')
        blocked = analyze(self.root, {'exclude': ['tests/fixture.log']})
        self.assertEqual(blocked['status'], 'BLOCKED')
        self.assertIn('dependency-not-included', [r['code'] for r in blocked['blockers']])

    def test_nested_agent_checkouts_are_reported_and_not_deleted(self):
        name = '.claude/worktrees/parallel/unmerged.py'
        self.put(name, 'unique work\n')
        plan = analyze(self.root)
        self.assertEqual(self.states(plan)['.claude/worktrees'], ('EXCLUDE', 'parallel-agent-checkouts'))
        self.assertNotIn(name, self.states(plan))
        self.assertEqual((self.root / name).read_text(), 'unique work\n')

    def test_review_changes_are_hash_bound_and_diff_separates_decisions(self):
        self.put('unknown.json', '{}')
        before = analyze(self.root)
        policy = decide(before, review_policy(before), 'unknown.json', 'include', 'Required reviewed configuration')
        after = analyze(self.root, policy)
        self.assertEqual(after['status'], 'PLANNED')
        diff = plan_diff(before, after)
        self.assertEqual(diff['content_changed'], [])
        self.assertEqual(diff['decisions_changed'], ['unknown.json'])
        self.assertTrue(diff['policy_changed'])
        self.put('unknown.json', '{"changed":1}')
        changed = analyze(self.root, policy)
        self.assertEqual(changed['status'], 'BLOCKED')
        self.assertEqual(self.states(changed)['unknown.json'][1], 'review-decision-stale')

    def test_decisions_replay_identically_after_relocation(self):
        self.put('unknown.json', '{}')
        initial = analyze(self.root)
        policy = decide(initial, review_policy(initial), 'unknown.json', 'include', 'Checked configuration')
        # No VCS or agent history is consulted to recover the decision.
        policy = json.loads(canonical(policy))
        first = analyze(self.root, policy)
        import shutil
        copy = self.base / 'other agent'
        shutil.copytree(self.root, copy)
        second = analyze(copy, policy)
        self.assertEqual(first, second)
        a = assemble(self.root, first, self.base / 'a')
        b = assemble(copy, second, self.base / 'b')
        self.assertEqual(a['archive_sha256'], b['archive_sha256'])
        self.assertEqual(verify_cached(self.base / 'a/release.zip', second)['status'], 'CANDIDATE')

    def test_missing_reviewed_file_is_not_silently_forgotten(self):
        path = self.put('unknown.json', '{}')
        initial = analyze(self.root)
        policy = decide(initial, review_policy(initial), 'unknown.json', 'exclude', 'Reviewed scratch data')
        path.unlink()
        plan = analyze(self.root, policy)
        self.assertEqual(plan['status'], 'BLOCKED')
        self.assertIn('review-decision-missing', [r['code'] for r in plan['blockers']])

    def test_analyze_first_does_not_publish_a_candidate(self):
        result = prepare(self.root, operation=Operation(state_directory=self.base / 'state'), review_only=True)
        self.assertEqual(result['status'], 'PLANNED')
        self.assertTrue((Path(result['audit']) / 'plan.json').is_file())
        self.assertFalse(list((self.root / 'releasecraft-output').glob('release-*')))

    def test_reviewed_binary_include_is_saved_and_published_exactly(self):
        import zipfile

        for number, name in enumerate(('screenshots/home.png', 'fixtures/input.bin', 'examples/resource.zip')):
            with self.subTest(path=name):
                payload = b'\x89PNG\x00public-fixture'
                path = self.put(name, payload)
                initial = analyze(self.root)
                self.assertEqual(self.states(initial)[name], ('UNRESOLVED', 'binary-needs-classification'))
                policy = decide(initial, review_policy(initial), name, 'include', 'Reviewed public fixture')
                saved = self.base / ('policy-' + str(number) + '.json')
                saved.write_bytes(canonical(policy))
                reviewed = analyze(self.root, json.loads(saved.read_bytes()))
                self.assertEqual(reviewed['status'], 'PLANNED')
                self.assertEqual(self.states(reviewed)[name], ('INCLUDE', 'reviewed-include'))
                output = self.base / ('binary-' + str(number))
                self.assertEqual(assemble(self.root, reviewed, output)['status'], 'CANDIDATE')
                with zipfile.ZipFile(output / 'release.zip') as archive:
                    self.assertEqual(archive.read(name), payload)
                self.assertEqual(path.read_bytes(), payload)
                path.unlink()

    def test_stale_binary_decisions_never_receive_dependency_approval(self):
        self.put('reader.py', 'open("asset.bin", "rb").read()\n')
        for action in ('include', 'exclude', 'review'):
            with self.subTest(action=action):
                path = self.put('asset.bin', b'\x00public-original')
                initial = analyze(self.root)
                policy = decide(initial, review_policy(initial), 'asset.bin', action, 'Recorded review decision')
                path.write_bytes(b'\x00changed-payload')
                changed = analyze(self.root, json.loads(canonical(policy)))
                self.assertEqual(changed['status'], 'BLOCKED')
                self.assertEqual(self.states(changed)['asset.bin'], ('UNRESOLVED', 'review-decision-stale'))
                self.assertIn('dependency-not-included', [r['code'] for r in changed['blockers']])
                with self.assertRaises(ReleaseError):
                    assemble(self.root, changed, self.base / ('stale-' + action))

    def test_explicit_binary_review_and_exclusion_block_required_resource(self):
        self.put('reader.py', 'open("asset.bin", "rb").read()\n')
        self.put('asset.bin', b'\x00public-original')
        initial = analyze(self.root)
        self.assertEqual(initial['status'], 'PLANNED')
        for action, expected in (('exclude', ('EXCLUDE', 'reviewed-exclude')), ('review', ('UNRESOLVED', 'user-review-required'))):
            with self.subTest(action=action):
                policy = decide(initial, review_policy(initial), 'asset.bin', action, 'Requires a deliberate decision')
                result = analyze(self.root, policy)
                self.assertEqual(result['status'], 'BLOCKED')
                self.assertEqual(self.states(result)['asset.bin'], expected)

    def test_binary_review_cannot_override_secret_or_private_state(self):
        name = 'screenshots/home.png'
        self.put(name, b'\x89PNG\x00' + ('gh' + 'p_' + 'Q' * 30).encode())
        initial = analyze(self.root)
        self.assertEqual(self.states(initial)[name][1], 'sensitive-content')
        with self.assertRaises(ReleaseError):
            decide(initial, review_policy(initial), name, 'include', 'Cannot approve a secret')
        policy = review_policy(initial)
        policy['decisions'][name] = {'action': 'include', 'reason': 'Manual policy cannot bypass scanning', 'sha256': next(r['sha256'] for r in initial['files'] if r['path'] == name)}
        result = analyze(self.root, policy)
        self.assertEqual(result['status'], 'BLOCKED')
        self.assertEqual(self.states(result)[name][1], 'sensitive-content')
        self.put('.codex/auth.json', b'\x00local-state')
        private = analyze(self.root)
        with self.assertRaises(ReleaseError):
            decide(private, review_policy(private), '.codex/auth.json', 'include', 'Cannot approve private state')

    def test_reviewed_binary_cli_plan_export_replay_and_mutation(self):
        import os
        import subprocess
        import sys

        name = 'screenshots/home.png'
        path = self.put(name, b'\x89PNG\x00public-fixture')
        initial = analyze(self.root)
        policy = decide(initial, review_policy(initial), name, 'include', 'Reviewed public screenshot for documentation')
        saved = self.base / 'reviewed.json'
        saved.write_bytes(canonical(policy))
        env = dict(os.environ, PYTHONNOUSERSITE='1', PYTHONDONTWRITEBYTECODE='1')
        env.pop('PYTHONPATH', None)

        def cli(args, expected):
            result = subprocess.run([sys.executable, '-m', 'releasecraft', *map(str, args)], env=env, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, expected, result.stderr.decode('utf8', errors='replace'))
            return json.loads(result.stdout)

        work = self.base / 'first work'
        self.assertEqual(cli(['plan', self.root, '--config', saved, '--work', work], 0)['status'], 'PLANNED')
        exported = self.base / 'exported.json'
        self.assertEqual(cli(['review-policy', work / 'plan.json', '--output', exported], 0)['status'], 'EXPORTED')
        self.assertEqual(json.loads(exported.read_bytes()), policy)
        replay = self.base / 'replay work'
        cli(['plan', self.root, '--config', exported, '--work', replay], 0)
        self.assertEqual((work / 'plan.json').read_bytes(), (replay / 'plan.json').read_bytes())
        cli(['build', self.root, '--plan', replay / 'plan.json', '--output', self.base / 'built'], 3)
        path.write_bytes(b'\x89PNG\x00changed-payload')
        blocked = cli(['plan', self.root, '--config', exported, '--work', self.base / 'changed'], 2)
        self.assertEqual(blocked['status'], 'BLOCKED')
        self.assertIn('review-decision-stale', [r['code'] for r in blocked['blocker_summary']['groups']])


if __name__ == '__main__':
    unittest.main()
