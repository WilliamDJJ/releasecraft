"""Local functions named like I/O APIs retain their own dependency contracts."""
from pathlib import Path
import tempfile
import unittest
from releasecraft.analyze import analyze


class LocalReaderTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.put('LICENSE','MIT License\nPermission is hereby granted\n')
        self.put('README.md','# Synthetic loader\n')

    def put(self,path,text):
        dest=self.root/path
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_text(text,encoding='utf8')

    def test_imported_local_load_and_module_alias_are_not_file_apis(self):
        self.put('helpers.py','import json\ndef load():\n return json.load(open("input.json"))\n')
        self.put('input.json','{}')
        for code in ('from helpers import load\nload()\n','import helpers as h\nh.load()\n'):
            with self.subTest(code=code):
                self.put('main.py',code)
                self.assertEqual(analyze(self.root)['status'],'PLANNED')

    def test_relative_local_loader_retains_missing_input_block(self):
        self.put('package/__init__.py','')
        self.put('package/io.py','def load():\n return open("needed.json").read()\n')
        self.put('package/main.py','from .io import load\nload()\n')
        plan=analyze(self.root)
        self.assertEqual(plan['status'],'BLOCKED')
        self.assertIn('missing-resource',{b['code'] for b in plan['blockers']})
        self.assertNotIn('dynamic-resource',{b['code'] for b in plan['blockers']})

    def test_same_file_load_with_literal_read_is_supported(self):
        self.put('main.py','def load():\n return open("input.txt").read()\nload()\n')
        self.put('input.txt','synthetic')
        self.assertEqual(analyze(self.root)['status'],'PLANNED')

    def test_excluded_loader_module_cannot_hide_dependency(self):
        self.put('helpers.py','def load():\n return 4\n')
        self.put('main.py','from helpers import load\nload()\n')
        plan=analyze(self.root,{'exclude':['helpers.py']})
        self.assertEqual(plan['status'],'BLOCKED')
        self.assertIn('dependency-not-included',{b['code'] for b in plan['blockers']})

    def test_dynamic_io_inside_local_helper_remains_blocked(self):
        self.put('helpers.py','def load(path):\n return open(path).read()\n')
        self.put('main.py','from helpers import load\nload("input.dat")\n')
        plan=analyze(self.root)
        self.assertEqual(plan['status'],'BLOCKED')
        self.assertIn('dynamic-resource',{b['code'] for b in plan['blockers']})

    def test_library_and_shadowed_loaders_keep_conservative_gate(self):
        self.put('helpers.py','def load():\n return 4\n')
        for code in ('import numpy as np\nnp.load(variable)\n','from helpers import load\nload=unknown\nload(variable)\n','from helpers import load\ndef run(load):\n load(variable)\n'):
            with self.subTest(code=code):
                self.put('main.py',code)
                self.assertEqual(analyze(self.root)['status'],'BLOCKED')

    def test_local_reexport_of_library_api_is_not_a_function_definition(self):
        self.put('helpers.py','from numpy import load\n')
        self.put('main.py','from helpers import load\nload(variable)\n')
        self.assertEqual(analyze(self.root)['status'],'BLOCKED')

    def test_decorated_loader_does_not_claim_plain_function_identity(self):
        self.put('main.py','@external_decorator\ndef load():\n return 4\nload(variable)\n')
        self.assertEqual(analyze(self.root)['status'],'BLOCKED')

    def test_aliased_library_reader_keeps_missing_resource_gate(self):
        self.put('main.py','from numpy import load as fetch\nfetch("needed.npy")\n')
        plan=analyze(self.root)
        self.assertEqual(plan['status'],'BLOCKED')
        self.assertIn('missing-resource',{b['code'] for b in plan['blockers']})

    def test_local_alias_retains_helper_inputs_and_frozen_identity(self):
        self.put('helpers.py','def load():\n return open("input.txt").read()\n')
        self.put('input.txt','data')
        self.put('main.py','from helpers import load as fetch\nfetch()\n')
        first=analyze(self.root)
        self.assertEqual(first['status'],'PLANNED')
        self.put('helpers.py','def load():\n return open("absent.txt").read()\n')
        changed=analyze(self.root)
        self.assertEqual(changed['status'],'BLOCKED')
        self.assertNotEqual(first['plan_sha256'],changed['plan_sha256'])

    def test_exception_match_and_attribute_shadowing_do_not_hide_reads(self):
        self.put('helpers.py','def load():\n return 4\n')
        for code in (
            'from helpers import load\ntry:\n pass\nexcept Exception as load:\n load(variable)\n',
            'from helpers import load\nmatch value:\n case {"reader": load}:\n  load(variable)\n',
            'import helpers as h\nh.load=unknown\nh.load(variable)\n',
            'from helpers import *\nload(variable)\n',
        ):
            with self.subTest(code=code):
                self.put('main.py',code)
                self.assertEqual(analyze(self.root)['status'],'BLOCKED')


if __name__=='__main__':unittest.main()
