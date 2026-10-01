"""Minimal independent reproductions from the seeded acceptance campaign."""
import json
from pathlib import Path
import tempfile
import unittest

from releasecraft.analyze import analyze


class BatchRegressions(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.put('LICENSE', 'Permission is hereby granted, free of charge, to any person obtaining a copy.\n')
        self.put('README.md', '# Synthetic local workflow\n')

    def put(self, name, value):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding='utf-8')

    def plan(self, policy=None):
        return analyze(self.root, policy)

    def test_import_module_alias_is_not_file_loader(self):
        self.put('plugins/__init__.py', '')
        self.put('plugins/worker.py', 'def answer(): return 7\n')
        for imports, call in (
            ('from importlib import import_module as load', 'load("plugins.worker")'),
            ('from importlib import import_module as load', 'load(name="plugins.worker")'),
            ('import importlib as loader', 'loader.import_module("plugins.worker")'),
        ):
            with self.subTest(call=call):
                self.put('main.py', imports + '\nassert ' + call + '.answer() == 7\n')
                plan = self.plan()
                self.assertEqual(plan['status'], 'PLANNED', plan['blockers'])
                edges = plan['dependencies']['main.py']['edges']
                self.assertIn({'target':'plugins/worker.py','kind':'dynamic-import-literal'}, edges)

    def test_aliased_import_keeps_exclusion_gate(self):
        self.put('worker.py', 'def answer(): return 7\n')
        self.put('main.py', 'from importlib import import_module as load\nload("worker")\n')
        plan = self.plan({'exclude':['worker.py']})
        self.assertIn('dependency-not-included', {b['code'] for b in plan['blockers']})

    def test_unknown_and_shadowed_import_alias_block(self):
        for code in (
            'from importlib import import_module as load\nload(variable)',
            'from importlib import import_module as load\nload = other\nload("worker")',
            'from importlib import import_module as load\ndef run(load):\n return load("worker")',
            'from importlib import import_module as load\nfrom other import *\nload("worker")',
        ):
            with self.subTest(code=code):
                self.put('main.py', code)
                plan = self.plan()
                self.assertEqual(plan['status'], 'BLOCKED')
                self.assertIn('dynamic-import', {b['code'] for b in plan['blockers']})

    def js(self, expression='path.join(__dirname, "assets", "input.dat")', extra=''):
        self.put('package.json', json.dumps({'name':'synthetic','version':'1.0.0','main':'lib/main.cjs'}))
        self.put('lib/main.cjs', 'const fs = require("node:fs");\nconst path = require("node:path");\n' + extra + '\nfs.readFileSync(' + expression + ', "utf8");\n')

    def test_literal_commonjs_dirname_join_retains_input(self):
        self.put('lib/assets/input.dat', 'fixture')
        self.js()
        plan = self.plan()
        self.assertEqual(plan['status'], 'PLANNED', plan['blockers'])
        selected = {row['path'] for row in plan['files'] if row['state']=='INCLUDE'}
        self.assertEqual(selected, {'LICENSE','README.md','package.json','lib/main.cjs','lib/assets/input.dat'})

    def test_commonjs_binding_alias_without_semicolon(self):
        self.put('package.json', '{"name":"synthetic","version":"1.0.0","main":"lib/main.cjs"}')
        self.put('lib/assets/input.dat', 'fixture')
        self.put('lib/main.cjs', 'const p = require("path")\nrequire("fs").readFileSync(p.join(__dirname, "assets/input.dat"));\n')
        self.assertEqual(self.plan()['status'], 'PLANNED')

    def test_commonjs_missing_input_has_no_root_fallback(self):
        self.put('assets/input.dat', 'wrong location')
        self.js()
        plan = self.plan()
        self.assertIn('missing-resource', {b['code'] for b in plan['blockers']})
        self.assertEqual(next(r['state'] for r in plan['files'] if r['path']=='assets/input.dat'), 'UNRESOLVED')

    def test_commonjs_required_exclusion_and_secret_block(self):
        self.put('lib/assets/input.dat', 'fixture')
        self.js()
        plan = self.plan({'exclude':['lib/assets/input.dat']})
        self.assertIn('dependency-not-included', {b['code'] for b in plan['blockers']})
        self.put('lib/assets/input.dat', 'ghp_' + 'S'*32)
        plan = self.plan({'include':['lib/assets/input.dat']})
        self.assertIn('sensitive-content', {b['code'] for b in plan['blockers']})

    def test_commonjs_unknown_escaped_and_combined_arguments_stay_dynamic(self):
        for expression in (
            'path.join(__dirname, variable)',
            'path.join(__dirname, "input\\x2edat")',
            'path.join(__dirname, "input.dat") + suffix',
            'path.join(__dirname, ...parts)',
            'path.join(other, "input.dat")',
        ):
            with self.subTest(expression=expression):
                self.js(expression)
                self.assertIn('dynamic-js-resource', {b['code'] for b in self.plan()['blockers']})

    def test_commonjs_shadowed_binding_stays_dynamic(self):
        for extra in (
            'path = other;',
            'path.join = other;',
            'function run(path) { return path; }',
            'const run = (path) => path;',
            '__dirname = elsewhere;',
            'function run(__dirname) { return __dirname; }',
            'function run(value) { const {path} = value; return path; }',
        ):
            with self.subTest(extra=extra):
                self.js(extra=extra)
                self.assertIn('dynamic-js-resource', {b['code'] for b in self.plan()['blockers']})

    def test_immediate_created_json_is_not_missing_input(self):
        for mode in ('w', 'w+', 'a', 'x'):
            with self.subTest(mode=mode):
                self.put('main.py', 'import json\nwith open("generated.json", mode=' + repr(mode) + ') as stream:\n    json.dump({"answer":7},stream)\nassert json.load(open("generated.json"))["answer"] == 7\n')
                plan = self.plan()
                self.assertEqual(plan['status'], 'PLANNED', plan['blockers'])
                self.assertEqual({row['path'] for row in plan['files']}, {'LICENSE','README.md','main.py'})

    def test_conditional_or_late_writer_does_not_hide_missing_input(self):
        examples = (
            'if condition:\n    with open("missing.json", "w") as f:\n        f.write("{}")\nopen("missing.json")',
            'open("missing.json")\nwith open("missing.json", "w") as f:\n    f.write("{}")',
            'with open("missing.json", "w") as f:\n    f.write("{}")\nunknown_operation()\nopen("missing.json")',
            'with open("missing.json", "r+") as f:\n    f.write("{}")\nopen("missing.json")',
            'with open("missing.json", "w") as f:\n    remove_file("missing.json")\nopen("missing.json")',
            'with open("missing.json", "w") as f:\n    f.write("{}")\nreader=lambda: open("missing.json")',
        )
        for code in examples:
            with self.subTest(code=code):
                self.put('main.py', code)
                self.assertIn('missing-resource', {b['code'] for b in self.plan()['blockers']})

    def test_generated_output_does_not_hide_different_missing_input(self):
        self.put('main.py', 'with open("output.json","w") as f:\n    f.write("{}")\nopen("input.json")\n')
        self.assertIn('missing-resource', {b['code'] for b in self.plan()['blockers']})

    def test_existing_generated_name_keeps_secret_and_exclusion_gates(self):
        self.put('main.py', 'with open("output.json","w") as f:\n    f.write("{}")\nopen("output.json")\n')
        self.put('output.json', '{}')
        plan = self.plan({'exclude':['output.json']})
        self.assertIn('dependency-not-included', {b['code'] for b in plan['blockers']})
        self.put('output.json', json.dumps({'token':'ghp_'+'S'*32}))
        plan = self.plan({'include':['output.json']})
        self.assertIn('sensitive-content', {b['code'] for b in plan['blockers']})

    def test_js_root_directory_import_resolves_index(self):
        self.put('package.json', '{"name":"synthetic","version":"1","main":"index.js"}')
        self.put('index.js', 'module.exports = 7;\n')
        self.put('test.js', 'if (require("./") !== 7) throw Error("value");\n')
        plan = self.plan()
        self.assertEqual(plan['status'], 'PLANNED', plan['blockers'])
        self.assertIn({'target':'index.js','kind':'js-import'}, plan['dependencies']['test.js']['edges'])

    def test_js_relative_import_cannot_fall_back_to_root(self):
        self.put('package.json', '{"name":"synthetic","version":"1"}')
        self.put('helper.js', 'module.exports = 7;\n')
        self.put('src/main.js', 'require("./helper");\n')
        self.assertIn('missing-resource', {b['code'] for b in self.plan()['blockers']})

    def test_repository_issue_link_is_not_a_missing_local_file(self):
        self.put('main.py', 'assert True\n')
        self.put('README.md', '# Example\n[Report](../../issues/new)\n[PR](../../pull/12)\n')
        self.put('docs/guide.md', '[Discuss](../../../discussions/12)\n')
        self.assertEqual(self.plan()['status'], 'PLANNED')

    def test_arbitrary_outside_document_file_still_blocks(self):
        self.put('main.py', 'assert True\n')
        for link in ('../../input.json','../../issues/private.json','../../other/new'):
            with self.subTest(link=link):
                self.put('README.md', '[Required]('+link+')\n')
                self.assertIn('missing-resource', {b['code'] for b in self.plan()['blockers']})

    def test_source_maintenance_files_and_runtime_profile(self):
        self.put('main.py', 'assert True\n')
        contents={'.eslintrc.json':'{"rules":{"semi":[2,"always"]}}','.travis.yml':'language: node_js\nnode_js: ["20"]\n','tox.ini':'[testenv]\ncommands = python -m unittest\n'}
        for name,data in contents.items():self.put(name,data)
        for mode,expected in (('source','INCLUDE'),('runtime','EXCLUDE')):
            with self.subTest(mode=mode):
                plan=self.plan({'mode':mode})
                self.assertEqual(plan['status'],'PLANNED',plan['blockers'])
                self.assertTrue(all(row['state']==expected for row in plan['files'] if row['path'] in contents))

    def test_maintenance_secret_and_invalid_json_cannot_bypass(self):
        self.put('main.py', 'assert True\n')
        self.put('.eslintrc.json','{"rules":')
        self.assertIn('invalid-json',{b['code'] for b in self.plan()['blockers']})
        self.put('.eslintrc.json',json.dumps({'token':'ghp_'+'S'*32}))
        self.assertIn('sensitive-content',{b['code'] for b in self.plan({'include':['.eslintrc.json']})['blockers']})

    def test_markdown_fenced_examples_are_not_local_dependencies(self):
        self.put('main.py', 'assert True\n')
        for fence, close in (('```js', '```'), ('~~~~ html', '~~~~~'), ('```', '')):
            with self.subTest(fence=fence, close=close):
                self.put('README.md', '# Example\n' + fence + '\nconst html = `<a href="${url}">example</a>`;\n![example](absent.png)\n' + close + '\n')
                self.assertEqual(self.plan()['status'], 'PLANNED')

    def test_markdown_real_assets_survive_fence_filter(self):
        self.put('main.py', 'assert True\n')
        self.put('logo.dat', 'synthetic picture')
        self.put('README.md', '<img src="logo.dat">\n```html\n<img src="missing-example.dat">\n```\n[Required](needed.dat)\n')
        plan = self.plan()
        self.assertIn('missing-resource', {b['code'] for b in plan['blockers']})
        self.assertIn({'target':'logo.dat','kind':'document-resource'}, plan['dependencies']['README.md']['edges'])
        self.put('needed.dat', 'fixture')
        self.assertEqual(self.plan()['status'], 'PLANNED')

    def test_markdown_fence_does_not_disable_secret_scan(self):
        self.put('main.py', 'assert True\n')
        self.put('README.md', '```text\n' + 'ghp_' + 'S'*32 + '\n```\n')
        self.assertIn('sensitive-content', {b['code'] for b in self.plan({'include':['README.md']})['blockers']})

    def test_single_module_literal_path_binding_is_required(self):
        self.put('input.json', '{}')
        for declaration, expression in (
            ('CONFIG = "input.json"', 'open(CONFIG)'),
            ('CONFIG: str = "input.json"', 'Path(CONFIG).read_text()'),
        ):
            with self.subTest(declaration=declaration):
                self.put('main.py', 'from pathlib import Path\n' + declaration + '\n' + expression + '\n')
                plan = self.plan()
                self.assertEqual(plan['status'], 'PLANNED', plan['blockers'])
                self.assertEqual(next(r['state'] for r in plan['files'] if r['path']=='input.json'), 'INCLUDE')
                self.assertIn('dependency-not-included', {b['code'] for b in self.plan({'exclude':['input.json']})['blockers']})

    def test_literal_path_binding_keeps_missing_and_secret_gates(self):
        self.put('main.py', 'CONFIG="input.json"\nopen(file=CONFIG)\n')
        self.assertIn('missing-resource', {b['code'] for b in self.plan()['blockers']})
        self.put('input.json', json.dumps({'token':'ghp_'+'S'*32}))
        self.assertIn('sensitive-content', {b['code'] for b in self.plan({'include':['input.json']})['blockers']})

    def test_ambiguous_path_binding_stays_dynamic(self):
        for code in (
            'CONFIG="input.json"\nCONFIG=other\nopen(CONFIG)',
            'if condition:\n CONFIG="input.json"\nopen(CONFIG)',
            'open(CONFIG)\nCONFIG="input.json"',
            'CONFIG="input.json"\ndef run(CONFIG):\n open(CONFIG)',
            'CONFIG="input.json"\nfrom other import *\nopen(CONFIG)',
            'CONFIG=make_path()\nopen(CONFIG)',
            'CONFIG="input.json"\ntry:\n pass\nexcept Exception as CONFIG:\n open(CONFIG)',
            'CONFIG="input.json"\nmatch value:\n case {"key": CONFIG}:\n  open(CONFIG)',
        ):
            with self.subTest(code=code):
                self.put('main.py', code)
                self.assertIn('dynamic-resource', {b['code'] for b in self.plan()['blockers']})

    def test_github_funding_is_source_maintenance(self):
        self.put('main.py', 'assert True\n')
        self.put('.github/FUNDING.yml', 'github: example-maintainer\n')
        for mode, expected in (('source','INCLUDE'),('runtime','EXCLUDE')):
            with self.subTest(mode=mode):
                plan=self.plan({'mode':mode})
                self.assertEqual(plan['status'],'PLANNED')
                self.assertEqual(next(r['state'] for r in plan['files'] if r['path']=='.github/FUNDING.yml'),expected)

    def test_funding_has_no_unknown_config_or_secret_bypass(self):
        self.put('main.py', 'assert True\n')
        self.put('.github/unknown.yml', 'setting: undecided\n')
        self.assertIn('unclassified-resource', {b['code'] for b in self.plan()['blockers']})
        self.put('.github/funding.yml', 'token: ghp_' + 'S'*32 + '\n')
        self.assertIn('sensitive-content', {b['code'] for b in self.plan({'include':['.github/funding.yml']})['blockers']})


if __name__ == '__main__':
    unittest.main()
