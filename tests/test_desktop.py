"""Translation/state contracts; separate native interaction is an acceptance gate."""
import json
import os
from pathlib import Path
import string
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from releasecraft.i18n import EN, ZH, translate
from releasecraft.preferences import language, save_language


class TranslationTests(unittest.TestCase):
    def test_translation_keys_and_format_fields_match(self):
        self.assertEqual(set(EN), set(ZH))
        formatter = string.Formatter()
        for key in EN:
            self.assertTrue(EN[key] and ZH[key], key)
            self.assertEqual(
                [field for _, field, _, _ in formatter.parse(EN[key]) if field],
                [field for _, field, _, _ in formatter.parse(ZH[key]) if field], key)

    def test_templates_keep_placeholders_and_machine_identifiers(self):
        for lang in ('en', 'zh'):
            self.assertIn('${API_KEY}', translate('safe_config', lang))
            self.assertIn('CANDIDATE', translate('candidate_limit', lang))

    def test_user_local_preference_round_trip_and_invalid_content(self):
        with tempfile.TemporaryDirectory() as temp:
            state = Path(temp) / 'private preferences'
            self.assertEqual(language(state), 'en')
            save_language('zh', state)
            self.assertEqual(language(state), 'zh')
            self.assertEqual(json.loads((state/'desktop-preferences.json').read_bytes()), {'schema': 1, 'language': 'zh'})
            for invalid in ([], {'schema': 1, 'language':'invalid'}, 'text'):
                (state/'desktop-preferences.json').write_text(json.dumps(invalid), encoding='utf8')
                self.assertEqual(language(state), 'en')
            with self.assertRaises(ValueError):
                save_language('xx', state)


@unittest.skipUnless(os.name == 'nt' or os.environ.get('DISPLAY'), 'Native Tk display required; tested separately on Windows')
class DesktopStateTests(unittest.TestCase):
    def setUp(self):
        import tkinter as tk
        from releasecraft.desktop import App
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.root = tk.Tk()
        self.root.withdraw()
        self.app = App(self.root, source=str(self.base/'project 空间'), state=self.base/'private')

    def tearDown(self):
        self.app.close()
        self.temp.cleanup()

    def set_language(self, code):
        self.app.language_choice.set('中文' if code == 'zh' else 'English')
        self.app.change_language()

    def test_language_switch_preserves_paths_options_and_result(self):
        app = self.app
        app.mode.set('research')
        app.choices['Tests'].set(False)
        original = (app.source.get(), app.output.get())
        app.result = {'status':'BLOCKED', 'problems':[{'code':'missing-resource','path':'数据 输入.json'}]}
        app.show_details()
        for code in ('zh','en','zh'):
            self.set_language(code)
            self.assertEqual((app.source.get(), app.output.get()), original)
            self.assertEqual(app.mode.get(), 'research')
            self.assertFalse(app.choices['Tests'].get())
            self.assertEqual(app.phase.get(), translate('blocked', code))
            self.assertIn('missing-resource', app.details_text.get('1.0','end'))
            self.assertIn('数据 输入.json', app.details_text.get('1.0','end'))
            self.assertEqual(app.result['status'], 'BLOCKED')
            self.root.update()
            self.assertLessEqual(app.details_close.winfo_rooty()+app.details_close.winfo_height(), app.details_window.winfo_rooty()+app.details_window.winfo_height())
        self.assertEqual(language(self.base/'private'), 'zh')

    def test_switch_during_active_operation_never_restarts_work(self):
        app = self.app
        entered, finish = threading.Event(), threading.Event()
        def run(source, output, policy, operation):
            operation.emit('Scanning', current='数据 输入.json', files=1, bytes_read=17, total_files=None)
            entered.set()
            finish.wait(5)
            return {'status':'CANCELLED', 'problems':[]}
        with patch('releasecraft.desktop.prepare', side_effect=run) as prepare:
            app.start()
            self.assertTrue(entered.wait(2))
            self.root.update()
            app.poll()
            operation = app.operation
            for code in ('zh','en','zh'):
                self.set_language(code)
                app.start()
                self.assertIs(app.operation, operation)
                self.assertTrue(app.busy)
                self.assertNotIn('disabled', app.language_selector.state())
                self.assertEqual(app.current.get(), '数据 输入.json')
            app.cancel()
            self.assertTrue(operation.cancelled.is_set())
            self.set_language('en')
            self.assertEqual(app.phase.get(), translate('cancelling','en'))
            finish.set()
            deadline = time.monotonic()+3
            while app.busy and time.monotonic() < deadline:
                self.root.update()
                time.sleep(.01)
            self.assertFalse(app.busy)
            self.assertEqual(app.result['status'], 'CANCELLED')
            self.assertEqual(prepare.call_count, 1)

    def test_all_footer_actions_fit_both_languages_and_advanced_modes(self):
        self.root.deiconify()
        for code in ('en','zh'):
            self.set_language(code)
            for expanded in (False, True):
                if self.app.advanced_visible != expanded:
                    self.app.toggle_advanced()
                self.root.update()
                right = self.root.winfo_rootx()+self.root.winfo_width()
                bottom = self.root.winfo_rooty()+self.root.winfo_height()
                for widget in (self.app.start_button,self.app.cancel_button,self.app.open_button,self.app.details_button,self.app.language_selector):
                    self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(), right)
                    self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(), bottom)

    def test_completed_summary_uses_measured_archive_counts(self):
        self.app.latest_event={'phase':'Analyzing','files':3,'total_files':4,'bytes_read':144,'elapsed_seconds':.1}
        self.app.result={'status':'CANDIDATE','problems':[],'payload_files':4,'archive_bytes':2345,'elapsed_seconds':.23}
        for code in ('en','zh'):
            self.set_language(code)
            self.assertEqual(self.app.metrics.get(),translate('metrics_result',code,files=4,bytes=2345,seconds='0.2'))
            self.assertNotIn('3 / 4',self.app.metrics.get())

    def test_storage_panel_switches_languages_and_preserves_selection(self):
        self.root.deiconify()
        self.app.show_storage()
        panel=self.app.storage_window
        deadline=time.monotonic()+5
        while panel.busy and time.monotonic()<deadline:
            self.root.update();time.sleep(.01)
        self.assertFalse(panel.busy)
        panel.data={'status':'AVAILABLE','bytes':123,'limit_bytes':999,'entries':4,'jobs':[{'id':'a'*32,'status':'CANDIDATE','audit_bytes':123,'retained':True,'cleanup':'CLEAN'}]}
        panel.render()
        panel.table.selection_set('a'*32)
        for code in ('zh','en'):
            self.set_language(code)
            self.root.update()
            self.assertEqual(panel.window.title(),translate('storage.title',code))
            self.assertEqual(panel.table.selection(),('a'*32,))
            self.assertIn('123',panel.usage.cget('text'))
            right=panel.window.winfo_rootx()+panel.window.winfo_width()
            bottom=panel.window.winfo_rooty()+panel.window.winfo_height()
            for widget in panel.buttons:
                self.assertLessEqual(widget.winfo_rootx()+widget.winfo_width(),right)
                self.assertLessEqual(widget.winfo_rooty()+widget.winfo_height(),bottom)
        panel.close()

    def test_cleanup_warning_does_not_replace_candidate_status(self):
        self.app.result={'status':'CANDIDATE','problems':[],'storage_warning':'private-staging-retained'}
        for code in ('en','zh'):
            self.set_language(code)
            self.assertEqual(self.app.phase.get(),translate('candidate',code))
            self.assertEqual(self.app.current.get(),translate('storage.warning',code))
        self.app.show_details()
        self.assertIn('private-staging-retained',self.app.details_text.get('1.0','end'))


class OpenOutputTests(unittest.TestCase):
    """Headless completion contracts; native file-manager interaction is separate."""
    def setUp(self):
        import queue
        from unittest.mock import Mock
        from releasecraft.desktop import App
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name)
        self.app = App.__new__(App)
        self.app.root = Mock()
        self.app.language = 'en'
        self.app.result = {'status': 'CANDIDATE', 'output': str(self.folder)}
        self.app.opener_results = queue.Queue()
        self.app.closing = False
        self.app.busy = False
        self.app.storage_window = None
        self.app.timer = None

    def tearDown(self):
        self.temp.cleanup()

    def start_opener(self, process=None, error=None):
        from types import SimpleNamespace
        with (patch('releasecraft.desktop.os', SimpleNamespace(name='posix')),
              patch('releasecraft.desktop.subprocess.Popen', return_value=process,
                    side_effect=error) as launch):
            self.app.open_output()
        self.assertEqual(launch.call_args.args[0], ['xdg-open', str(self.folder)])
        self.assertFalse(launch.call_args.kwargs['shell'])

    def child(self, code):
        from unittest.mock import Mock
        entered, release = threading.Event(), threading.Event()
        def wait():
            entered.set()
            if not release.wait(3):
                raise OSError('Synthetic opener did not finish')
            return code
        process = Mock(wait=Mock(side_effect=wait))
        self.addCleanup(release.set)
        return process, entered, release

    def await_result(self):
        deadline = time.monotonic() + 2
        while self.app.opener_results.empty() and time.monotonic() < deadline:
            time.sleep(.005)
        self.assertFalse(self.app.opener_results.empty())
        self.app.poll_open_output()

    def test_opener_launch_exception_is_bilingual(self):
        for code in ('en', 'zh'):
            with self.subTest(language=code), patch('releasecraft.desktop.messagebox.showerror') as show:
                self.app.language = code
                self.start_opener(error=OSError('Synthetic launch failure'))
                show.assert_called_once_with(translate('open_error_title', code),
                                             translate('open_error', code), parent=self.app.root)

    def test_opener_nonzero_exit_reports_current_language(self):
        process, entered, release = self.child(7)
        with patch('releasecraft.desktop.messagebox.showerror') as show:
            self.start_opener(process)
            self.assertTrue(entered.wait(1))
            self.app.poll_open_output()
            show.assert_not_called()
            # A pending child does not block the main thread or language changes.
            self.app.language = 'zh'
            release.set()
            self.await_result()
            show.assert_called_once_with(translate('open_error_title', 'zh'),
                                         translate('open_error', 'zh'), parent=self.app.root)
            self.app.poll_open_output()
            self.assertEqual(show.call_count, 1)
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_opener_zero_exit_has_no_error(self):
        process, entered, release = self.child(0)
        with patch('releasecraft.desktop.messagebox.showerror') as show:
            self.start_opener(process)
            self.assertTrue(entered.wait(1))
            release.set()
            self.await_result()
            show.assert_not_called()
        process.kill.assert_not_called()
        process.terminate.assert_not_called()

    def test_close_with_pending_opener_does_not_wait_or_kill(self):
        process, entered, release = self.child(1)
        with patch('releasecraft.desktop.messagebox.showerror') as show:
            self.start_opener(process)
            self.assertTrue(entered.wait(1))
            self.app.close()
            self.app.root.destroy.assert_called_once()
            self.assertFalse(release.is_set())
            release.set()
            self.await_result()
            show.assert_not_called()
        process.kill.assert_not_called()
        process.terminate.assert_not_called()
        self.app.root.after.assert_not_called()


if __name__ == '__main__':
    unittest.main()
