"""Compact native desktop client of the deterministic release core."""
from __future__ import annotations
import argparse
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter import font as tkfont
from .i18n import translate, action_key
from .preferences import language, save_language
from .managed import OUTPUT_NAME, prepare
from .operation import Operation, Cancelled
from .policy import load_policy
from .safety import ReleaseError, digest, findings
from .directory import Directory

from . import __version__

BUILD = __version__
CATEGORIES = {
    "Tests": ["tests/**", "test/**", "**/tests/**"],
    "Documentation": ["docs/**", "doc/**", "**/docs/**"],
    "Notebooks": ["*.ipynb", "**/*.ipynb"],
    "Samples": ["examples/**", "samples/**", "sample_data/**"],
    "Reproducibility": ["benchmarks/**", "reproduce/**", "reproducibility/**"],
}


def scope_policy(choices, policy_path=None, mode="source", strip_outputs=True, excludes=()):
    policy = load_policy(policy_path)
    policy["mode"] = mode
    policy["notebook_outputs"] = "strip" if strip_outputs else "preserve"
    policy["exclude"] = [*policy["exclude"], *excludes]
    for category, patterns in CATEGORIES.items():
        if not choices.get(category, True):
            policy["exclude"].extend(patterns)
    return load_policy(value=policy)


def safe_label(value):
    value = str(value)
    return "[redacted path " + digest(value.encode())[:12] + "]" if findings(value.encode()) else value


class App:
    def __init__(self, root, source="", output="", state=None):
        self.root, self.state_directory = root, state
        self.busy = False
        self.closing = False
        self.result = None
        self.progress_events = queue.Queue(maxsize=1)
        self.results = queue.Queue(maxsize=1)
        self.opener_results = queue.Queue()
        self.operation = None
        self.language = language(state)
        self.localized = []
        self.latest_event = None
        self.details_window = None
        self.preference_warning = False
        self.storage_window = None
        self.review_window = None
        root.title(self.tr("title"))
        root.minsize(660, 460)
        root.geometry("720x490")
        root.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(root)
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Title.TLabel", font=("Segoe UI", 17, "bold"))
        style.configure("Muted.TLabel", foreground="#526277")
        style.configure("Status.TLabel", font=("Segoe UI", 10, "bold"))
        outer = ttk.Frame(root, padding=16)
        outer.pack(fill="both", expand=True)
        outer.columnconfigure(1, weight=1)
        title = ttk.Frame(outer)
        title.grid(row=0, column=0, columnspan=3, sticky="ew", pady=(0, 13))
        mark = tk.Canvas(title, width=42, height=42, highlightthickness=0, background="#216eaa")
        mark.create_text(21, 21, text="RC", fill="white", font=("Segoe UI", 14, "bold"))
        mark.pack(side="left", padx=(0, 10))
        ttk.Label(title, text="Releasecraft", style="Title.TLabel").pack(side="left")
        self.language_choice = tk.StringVar(value="中文" if self.language == "zh" else "English")
        self.language_selector = ttk.Combobox(title, textvariable=self.language_choice, values=("English", "中文"), width=9, state="readonly")
        self.language_selector.pack(side="right", padx=(8, 0))
        self.language_selector.bind("<<ComboboxSelected>>", self.change_language)
        self.build_label = ttk.Label(title, style="Muted.TLabel")
        self.build_label.pack(side="right", anchor="s")
        self.source = tk.StringVar(value=source)
        self.output = tk.StringVar(value=output or (str(Path(source) / OUTPUT_NAME) if source else ""))
        self.automatic_output = not bool(output)
        self.controls = []
        self.widget(ttk.Label, outer, "source").grid(row=1, column=0, sticky="w", padx=(0, 10))
        self.source_entry = ttk.Entry(outer, textvariable=self.source)
        self.source_entry.grid(row=1, column=1, sticky="ew", pady=4)
        self.source_browse = self.widget(ttk.Button, outer, "browse", command=self.choose_source)
        self.source_browse.grid(row=1, column=2, padx=(8, 0))
        self.widget(ttk.Label, outer, "output").grid(row=2, column=0, sticky="w")
        self.output_entry = ttk.Entry(outer, textvariable=self.output)
        self.output_entry.grid(row=2, column=1, sticky="ew", pady=4)
        self.output_browse = self.widget(ttk.Button, outer, "elsewhere", command=self.choose_output)
        self.output_browse.grid(row=2, column=2, padx=(8, 0))
        self.controls += [self.source_entry, self.source_browse, self.output_entry, self.output_browse]
        self.source.trace_add("write", self.source_changed)
        self.output_entry.bind("<KeyRelease>", lambda event: setattr(self, "automatic_output", False))
        self.widget(ttk.Label, outer, "no_edit", style="Muted.TLabel").grid(row=3, column=1, columnspan=2, sticky="w", pady=(2, 10))
        scope = self.widget(ttk.LabelFrame, outer, "scope", padding=(10, 8))
        scope.grid(row=4, column=0, columnspan=3, sticky="ew")
        self.choices = {}
        for index, label in enumerate(CATEGORIES):
            variable = tk.BooleanVar(value=True)
            self.choices[label] = variable
            box = self.widget(ttk.Checkbutton, scope, "scope." + label, variable=variable)
            box.grid(row=0, column=index, sticky="w", padx=(0, 10))
            self.controls.append(box)
        self.widget(ttk.Label, scope, "gates", style="Muted.TLabel").grid(row=1, column=0, columnspan=5, sticky="w", pady=(5, 0))
        self.advanced_button = ttk.Button(outer, text="▸ Advanced options", command=self.toggle_advanced)
        self.advanced_button.grid(row=5, column=0, columnspan=3, sticky="w", pady=8)
        self.controls.append(self.advanced_button)
        self.advanced = ttk.Frame(outer, padding=(10, 4))
        self.advanced_visible = False
        self.advanced.columnconfigure(1, weight=1)
        self.mode = tk.StringVar(value="source")
        self.profile_text = tk.StringVar()
        self.policy_path = tk.StringVar()
        self.exclude_patterns = tk.StringVar()
        self.strip_outputs = tk.BooleanVar(value=True)
        self.widget(ttk.Label, self.advanced, "profile").grid(row=0, column=0, sticky="w")
        profile = self.profile = ttk.Combobox(self.advanced, textvariable=self.profile_text, state="readonly", width=18)
        profile.bind("<<ComboboxSelected>>", self.profile_changed)
        profile.grid(row=0, column=1, sticky="w")
        strip = self.widget(ttk.Checkbutton, self.advanced, "strip", variable=self.strip_outputs)
        strip.grid(row=0, column=2, padx=6)
        self.widget(ttk.Label, self.advanced, "policy").grid(row=1, column=0, sticky="w", pady=4)
        config = ttk.Entry(self.advanced, textvariable=self.policy_path)
        config.grid(row=1, column=1, sticky="ew", padx=5)
        config_browse = self.widget(ttk.Button, self.advanced, "choose", command=self.choose_policy)
        config_browse.grid(row=1, column=2)
        self.widget(ttk.Label, self.advanced, "exclude").grid(row=2, column=0, sticky="w")
        excludes = ttk.Entry(self.advanced, textvariable=self.exclude_patterns)
        excludes.grid(row=2, column=1, columnspan=2, sticky="ew", padx=5)
        self.widget(ttk.Label, self.advanced, "patterns_help", style="Muted.TLabel").grid(row=3, column=0, columnspan=3, sticky="w", pady=4)
        self.controls += [profile, strip, config, config_browse, excludes]
        progress = self.widget(ttk.LabelFrame, outer, "progress", padding=10)
        progress.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(2, 8))
        self.phase = tk.StringVar()
        self.current = tk.StringVar()
        self.metrics = tk.StringVar()
        ttk.Label(progress, textvariable=self.phase, style="Status.TLabel").pack(anchor="w")
        self.bar = ttk.Progressbar(progress, mode="determinate", maximum=100)
        self.bar.pack(fill="x", pady=8)
        current_area = ttk.Frame(progress, height=tkfont.nametofont("TkDefaultFont").metrics("linespace") * 3)
        current_area.pack(fill="x")
        current_area.pack_propagate(False)
        ttk.Label(current_area, textvariable=self.current, style="Muted.TLabel", wraplength=640).pack(anchor="w")
        ttk.Label(progress, textvariable=self.metrics).pack(anchor="w", pady=(7, 0))
        footer = ttk.Frame(outer)
        footer.grid(row=8, column=0, columnspan=3, sticky="ew", pady=(6, 0))
        self.details_button = self.widget(ttk.Button, footer, "details", command=self.show_details, state="disabled")
        self.details_button.pack(side="left")
        self.widget(ttk.Button, footer, "config_help", command=self.config_help).pack(side="left", padx=6)
        self.open_button = self.widget(ttk.Button, footer, "open_output", command=self.open_output, state="disabled")
        self.open_button.pack(side="right")
        self.cancel_button = self.widget(ttk.Button, footer, "cancel", command=self.cancel, state="disabled")
        self.cancel_button.pack(side="right", padx=6)
        self.start_button = self.widget(ttk.Button, footer, "prepare", command=self.start)
        self.start_button.pack(side="right")
        self.storage_button = self.widget(ttk.Button, outer, "storage.title", command=self.show_storage)
        self.storage_button.grid(row=10, column=0, sticky="w", pady=(8,0))
        self.analyze_button = self.widget(ttk.Button, outer, "review.analyze", command=lambda: self.start(review_only=True))
        self.analyze_button.grid(row=10, column=1, sticky="w", pady=(8,0))
        self.review_button = self.widget(ttk.Button, outer, "review.title", command=self.show_review, state="disabled")
        self.review_button.grid(row=10, column=2, sticky="e", pady=(8,0))
        self.controls.append(self.analyze_button)
        self.refresh_language()
        self.timer = root.after(70, self.poll)

    def tr(self, key, **values):
        return translate(key, self.language, **values)

    def widget(self, kind, parent, key, **options):
        widget = kind(parent, text=self.tr(key), **options)
        self.localized.append((widget, key))
        return widget

    def change_language(self, event=None):
        self.language = "zh" if self.language_choice.get() == "中文" else "en"
        try:
            save_language(self.language, self.state_directory)
            self.preference_warning = False
        except (OSError, ReleaseError):
            self.preference_warning = True
        self.refresh_language()

    def profile_changed(self, event=None):
        codes = ("source", "runtime", "research")
        if self.profile.current() >= 0:
            self.mode.set(codes[self.profile.current()])

    def refresh_language(self):
        self.root.title(self.tr("title"))
        self.build_label.configure(text=self.tr("preview", build=BUILD))
        for widget, key in self.localized:
            widget.configure(text=self.tr(key))
        self.profile.configure(values=tuple(self.tr("profile." + code) for code in ("source", "runtime", "research")))
        self.profile_text.set(self.tr("profile." + self.mode.get()))
        self.advanced_button.configure(text=self.tr("advanced_open" if self.advanced_visible else "advanced_closed"))
        self.render_progress()
        if self.details_window is not None and self.details_window.winfo_exists():
            self.render_details()
        if self.storage_window is not None and self.storage_window.window.winfo_exists():
            self.storage_window.refresh_language()
        if self.review_window is not None and self.review_window.window.winfo_exists():
            self.review_window.refresh_language()
        if self.preference_warning:
            self.current.set(self.tr("preference_error"))
        self.resize()

    def render_progress(self):
        event = self.latest_event
        if self.busy:
            if self.operation.cancelled.is_set():
                self.phase.set(self.tr("cancelling"))
                self.current.set(self.tr("cancel_wait"))
            elif event:
                self.phase.set(self.tr(event["phase"]))
                current = safe_label(event.get("current", ""))
                self.current.set(current if len(current) <= 180 else current[:80] + " … " + current[-90:])
            else:
                self.phase.set(self.tr("workspace"))
                self.current.set(self.tr("no_execution"))
        elif self.result is not None:
            status = self.result["status"]
            self.phase.set(self.tr({"CANDIDATE":"candidate", "BLOCKED":"blocked", "CANCELLED":"cancelled", "PLANNED":"PLANNED"}.get(status, "failed")))
            self.current.set(self.tr("storage.warning") if self.result.get("storage_warning") else self.tr("candidate_limit" if status == "CANDIDATE" else "source_unchanged"))
        else:
            self.phase.set(self.tr("idle"))
            self.current.set(self.tr("no_execution"))
        event = event or {}
        if not self.busy and self.result is not None and self.result['status'] == 'CANDIDATE':
            self.metrics.set(self.tr('metrics_result', files=self.result.get('payload_files', self.tr('unknown')),
                                    bytes=self.result.get('archive_bytes', self.tr('unknown')),
                                    seconds=f"{self.result['elapsed_seconds']:.1f}" if 'elapsed_seconds' in self.result else '—'))
            return
        byte_count = event.get("bytes_read", event.get("bytes_written", event.get("archive_bytes", "—")))
        self.metrics.set(self.tr("metrics", files=event.get("files", "—"), total=event.get("total_files") if event.get("total_files") is not None else self.tr("unknown"), bytes=byte_count, seconds=f"{event['elapsed_seconds']:.1f}" if "elapsed_seconds" in event else "—"))

    def resize(self):
        self.root.update_idletasks()
        width = max(720, self.root.winfo_reqwidth())
        height = max(490, self.root.winfo_reqheight())
        self.root.geometry(f"{width}x{height}")
        self.root.minsize(width, height)

    def source_changed(self, *args):
        if self.automatic_output and self.source.get().strip():
            self.output.set(str(Path(self.source.get().strip()) / OUTPUT_NAME))

    def choose_source(self):
        path = filedialog.askdirectory(parent=self.root, title=self.tr("choose_source"), mustexist=True)
        if path:
            self.automatic_output = True
            self.source.set(path)

    def choose_output(self):
        path = filedialog.askdirectory(parent=self.root, title=self.tr("choose_output"), mustexist=True)
        if path:
            self.automatic_output = False
            self.output.set(str(Path(path) / OUTPUT_NAME))

    def choose_policy(self):
        path = filedialog.askopenfilename(parent=self.root, title=self.tr("choose_policy"), filetypes=[(self.tr("json_policy"), "*.json")])
        if path:
            self.policy_path.set(path)

    def toggle_advanced(self):
        self.advanced_visible = not self.advanced_visible
        if self.advanced_visible:
            self.advanced.grid(row=6, column=0, columnspan=3, sticky="ew")
        else:
            self.advanced.grid_remove()
        self.advanced_button.configure(text=self.tr("advanced_open" if self.advanced_visible else "advanced_closed"))
        self.resize()

    def record_progress(self, event):
        try:
            self.progress_events.get_nowait()
        except queue.Empty:
            pass
        try:
            self.progress_events.put_nowait(event)
        except queue.Full:
            pass

    def start(self, *, review_only=False):
        if self.busy:
            return
        if not self.source.get().strip() or not self.output.get().strip():
            messagebox.showinfo(self.tr("choose_folders_title"), self.tr("choose_folders"), parent=self.root)
            return
        try:
            policy = scope_policy({k:v.get() for k,v in self.choices.items()}, self.policy_path.get().strip() or None,
                                  self.mode.get(), self.strip_outputs.get(), [x.strip() for x in self.exclude_patterns.get().split(";") if x.strip()])
        except (OSError, ReleaseError, ValueError, TypeError):
            messagebox.showerror(self.tr("policy_rejected_title"), self.tr("policy_rejected"), parent=self.root)
            return
        source, output = self.source.get().strip(), self.output.get().strip()
        self.result = None
        self.review_button.state(["disabled"])
        if self.review_window is not None and self.review_window.window.winfo_exists():
            self.review_window.window.destroy()
        self.latest_event = None
        while not self.progress_events.empty():
            self.progress_events.get_nowait()
        self.busy = True
        self.operation = Operation(self.record_progress, state_directory=self.state_directory)
        for control in self.controls:
            control.state(["disabled"])
        self.start_button.state(["disabled"])
        self.cancel_button.state(["!disabled"])
        self.details_button.state(["disabled"])
        self.open_button.state(["disabled"])
        self.render_progress()
        def work():
            try:
                result = prepare(source, output, policy, self.operation, review_only=True) if review_only else prepare(source, output, policy, self.operation)
            except Cancelled:
                result = {"status":"CANCELLED", "problems":[]}
            except Exception:
                result = {"status":"FAILED", "problems":[{"code":"output-or-operation-rejected"}]}
            result['elapsed_seconds'] = time.monotonic() - self.operation.started
            self.results.put(result)
        threading.Thread(target=work, daemon=False).start()

    def cancel(self):
        if self.busy:
            self.operation.cancelled.set()
            self.render_progress()
            self.cancel_button.state(["disabled"])

    def poll(self):
        if self.timer is not None:
            self.root.after_cancel(self.timer)
            self.timer = None
        self.poll_open_output()
        try:
            event = self.progress_events.get_nowait()
        except queue.Empty:
            event = None
        if event and self.busy and not self.operation.cancelled.is_set():
            self.latest_event = event
            self.render_progress()
            total, files = event.get("total_files"), event.get("files")
            if total is None:
                if str(self.bar['mode']) != "indeterminate":
                    self.bar.configure(mode="indeterminate")
                    self.bar.start(70)
            else:
                self.bar.stop()
                self.bar.configure(mode="determinate", maximum=max(total, 1), value=files or 0)
        try:
            result = self.results.get_nowait()
        except queue.Empty:
            result = None
        if result is not None:
            self.result, self.busy = result, False
            self.bar.stop()
            self.bar.configure(mode="determinate", maximum=1, value=int(result["status"]=="CANDIDATE"))
            for control in self.controls:
                control.state(["!disabled"])
            self.start_button.state(["!disabled"])
            self.cancel_button.state(["disabled"])
            self.render_progress()
            if result.get("problems") or result.get("storage_warning"):
                self.details_button.state(["!disabled"])
            if result.get("audit"):
                self.review_button.state(["!disabled"])
            if result.get("output"):
                self.open_button.state(["!disabled"])
            if self.closing:
                self.close()
                return
        self.timer = self.root.after(70, self.poll)

    def show_review(self):
        if self.busy or not self.result or not self.result.get("audit"):
            return
        if self.review_window is not None and self.review_window.window.winfo_exists():
            self.review_window.window.lift()
            return
        from .review_ui import ReviewWindow
        try:
            self.review_window = ReviewWindow(self)
        except (OSError, ReleaseError, ValueError, TypeError):
            messagebox.showerror(self.tr("review.title"), self.tr("review.load_error"), parent=self.root)

    def show_storage(self):
        if self.storage_window is not None and self.storage_window.window.winfo_exists():
            self.storage_window.window.lift()
            return
        from .storage_ui import StorageWindow
        self.storage_window = StorageWindow(self)

    def show_details(self):
        if not self.result:
            return
        if self.details_window is not None and self.details_window.winfo_exists():
            self.details_window.lift()
            return
        window = self.details_window = tk.Toplevel(self.root)
        window.geometry("800x420")
        window.minsize(500, 260)
        self.details_close = ttk.Button(window, command=window.destroy)
        self.details_close.pack(side="bottom", pady=8)
        self.details_text = tk.Text(window, wrap="word", padx=14, pady=14, font=("Segoe UI", 10))
        self.details_text.pack(fill="both", expand=True)
        self.render_details()

    def render_details(self):
        self.details_window.title(self.tr("details_title"))
        self.details_close.configure(text=self.tr("close"))
        text = self.details_text
        text.configure(state="normal")
        text.delete("1.0", "end")
        if self.result.get("storage_warning"):
            text.insert("end", self.tr("storage.warning") + "\n" + self.result['storage_warning'] + "\n\n")
        for problem in self.result.get("problems", [])[:1000]:
            code = problem["code"]
            path = problem.get("path", problem.get("path_id", ""))
            action = self.tr("storage.blocked" if code == "private-storage-blocked" else "output_rejected" if code == "output-or-operation-rejected" else action_key(code))
            text.insert("end", f"{code}  {safe_label(path)}\n{action}\n\n")
        if len(self.result.get("problems", [])) > 1000:
            text.insert("end", self.tr("details_limit") + "\n")
        text.configure(state="disabled")

    def config_help(self):
        messagebox.showinfo(self.tr("safe_config_title"), self.tr("safe_config"), parent=self.root)

    def open_output(self):
        if not self.result or not self.result.get("output"):
            return
        try:
            with Directory(self.result["output"]) as directory:
                if os.name == "nt":
                    os.startfile(str(directory.path))
                else:
                    process = subprocess.Popen(["xdg-open", str(directory.path)], shell=False,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    results = self.opener_results
                    def completed():
                        try:
                            code = process.wait()
                        except OSError:
                            code = 1
                        results.put(code)
                    # Some openers stay alive with the file manager. Do not wait on
                    # Tk's thread or terminate that application when this window closes.
                    threading.Thread(target=completed, daemon=True).start()
        except (OSError, ReleaseError):
            messagebox.showerror(self.tr("open_error_title"), self.tr("open_error"), parent=self.root)

    def poll_open_output(self):
        try:
            code = self.opener_results.get_nowait()
        except queue.Empty:
            return
        if code != 0 and not self.closing:
            messagebox.showerror(self.tr("open_error_title"), self.tr("open_error"), parent=self.root)

    def close(self):
        if self.storage_window is not None and self.storage_window.window.winfo_exists() and self.storage_window.busy:
            self.storage_window.window.lift()
            return
        if self.busy:
            self.closing = True
            self.cancel()
        else:
            self.closing = True
            if self.timer is not None:
                self.root.after_cancel(self.timer)
                self.timer = None
            self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description="Releasecraft native desktop window")
    parser.add_argument("--source", default="")
    parser.add_argument("--output", default="")
    parser.add_argument("--state-directory", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.name == "nt":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass
    root = tk.Tk()
    App(root, args.source, args.output, args.state_directory)
    root.mainloop()
    return 0


if __name__ == "__main__":
    main()
