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


if __name__ == '__main__':
    unittest.main()
