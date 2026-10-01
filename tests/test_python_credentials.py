"""Credential expressions differ from literal config values; raw secrets still gate."""
from pathlib import Path
import tempfile
import unittest
from releasecraft.analyze import analyze
from releasecraft.build import assemble, verify_archive
from releasecraft.safety import findings


class PythonCredentialTests(unittest.TestCase):
    def test_environment_lookup_is_not_a_literal_credential(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)/'source';root.mkdir()
            (root/'LICENSE').write_text('MIT License\nPermission is hereby granted\n')
            (root/'README.md').write_text('# Configuration\nCredentials come from the environment.\n')
            (root/'main.py').write_text('import os\nSECRET_KEY = os.environ.get("SECRET_KEY")\n')
            plan=analyze(root)
            self.assertEqual(plan['status'],'PLANNED',plan['blockers'])
            report=assemble(root,plan,Path(temp)/'output')
            self.assertEqual(report['status'],'CANDIDATE')
            self.assertEqual(verify_archive(Path(temp)/'output/release.zip')['status'],'CANDIDATE')

    def test_parameter_reference_and_transform_are_not_literal_values(self):
        for code in (
            'def use(self):\n    secret_key = self.secret_keys[-1]\n',
            'from codecs import encode\ndef use(secret_key):\n    secret_key = encode(secret_key)\n',
            'def use(credentials):\n    PASSWORD = credentials.password\n',
        ):
            with self.subTest(code=code):
                self.assertFalse(findings(code.encode(),python_source=True))

    def test_config_or_unknown_name_is_not_exempted_by_python_syntax(self):
        for data in (b'PASSWORD=abc123\n',b'SECRET_KEY=unbound_value\n',b'PASSWORD=123456\n'):
            self.assertTrue(findings(data))
            self.assertTrue(findings(data,python_source=True))
        self.assertTrue(findings(b'SECRET_KEY=self.secret_keys[-1]\n',python_source=True))

    def test_literal_default_and_encoded_literal_stay_blocked(self):
        for code in (
            'import os\nPASSWORD = os.getenv("PASSWORD", "sample-sensitive-value")\n',
            'import os\nPASSWORD = os.environ.get("PASSWORD", "sample-sensitive-value")\n',
            'from codecs import decode\nPASSWORD = decode("synthetic-base64-material")\n',
            'PASS' + 'WORD="sample-sensitive-value"\n',
        ):
            with self.subTest(code=code):
                self.assertTrue(findings(code.encode(),python_source=True))

    def test_provider_tokens_comments_and_docstrings_are_still_scanned(self):
        value='ghp_'+'X'*30
        for code in ('# '+value+'\n', '"""'+value+'"""\n', 'def use(self):\n secret_key = self.secret_keys[-1]  # '+value+'\n'):
            self.assertIn('provider-token',{r for r,_ in findings(code.encode(),python_source=True)})

    def test_syntax_error_stays_conservative(self):
        self.assertTrue(findings(b'def broken(:\n PASSWORD=os.getenv("PASSWORD")\n',python_source=True))

    def test_multiple_statements_do_not_create_line_wide_exemption(self):
        self.assertTrue(findings(b'import os\nPASSWORD=os.getenv("PASSWORD"); PASSWORD=abc123\n',python_source=True))

    def test_environment_diagnostic_line_excludes_preceding_blank_lines(self):
        self.assertIn(('credential-environment',3), findings(b'\n\nPASSWORD=abc123\n'))

    def test_shadowed_imports_and_parameter_rebinding_stay_conservative(self):
        for code in (
            'import os\nos = custom\nPASSWORD = os.getenv("PASSWORD")\n',
            'import os\ndef f(os):\n PASSWORD = os.getenv("PASSWORD")\n',
            'from os import getenv\ngetenv = custom\nPASSWORD = getenv("PASSWORD")\n',
            'def f(value):\n value = 123456\n PASSWORD = value\n',
            'def f(value=123456):\n PASSWORD = value\n',
            'from codecs import encode\ndef f(value, encode):\n PASSWORD = encode(value)\n',
        ):
            with self.subTest(code=code):
                self.assertTrue(findings(code.encode(),python_source=True))

    def test_code_looking_string_never_grants_expression_exemption(self):
        text='example = """\nimport os\nPASSWORD = os.getenv("PASSWORD")\n"""\n'
        self.assertTrue(findings(text.encode(),python_source=True))

    def test_parameter_reassignment_to_reference_remains_supported(self):
        text='from codecs import encode\ndef f(secret_key):\n secret_key = encode(secret_key)\n'
        self.assertFalse(findings(text.encode(),python_source=True))


if __name__=='__main__':unittest.main()
