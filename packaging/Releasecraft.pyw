"""Double-click entry: install the trusted bundled wheel locally, then open its GUI."""
from pathlib import Path
import os
import queue
import subprocess
import sys
import threading
import hashlib
import json


def main():
    folder = Path(__file__).resolve().parent
    try:
        import tkinter as tk
        from tkinter import ttk, messagebox
    except ImportError:
        if os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(None, "Python with Tcl/Tk is required. / 需要带 Tcl/Tk 的 Python。", "Releasecraft", 0x10)
        else:
            raise SystemExit("Python tkinter is required; install your distribution's Python Tk package.")
        return
    if os.name == "nt":
        import ctypes
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (OSError, AttributeError):
            pass
    root = tk.Tk()
    root.withdraw()
    try:
        wheels = list((folder / "wheels").glob("releasecraft-*.whl"))
        if len(wheels) != 1:
            raise ValueError("Expected one bundled wheel")
        manifest = json.loads((folder / "DISTRIBUTION.json").read_bytes())
        expected = next(row["sha256"] for row in manifest["files"] if row["path"] == "wheels/" + wheels[0].name)
        if hashlib.sha256(wheels[0].read_bytes()).hexdigest() != expected:
            raise ValueError("Bundled wheel integrity mismatch")
        # This is the explicitly launched distribution's own wheel, not selected project code.
        sys.path.insert(0, str(wheels[0]))
        from releasecraft.i18n import translate
        from releasecraft.preferences import language, save_language
        from releasecraft.safety import ReleaseError
    except (OSError, ValueError, KeyError, TypeError, StopIteration, ImportError):
        messagebox.showerror("Releasecraft", "Incomplete or changed distribution. Extract a fresh trusted bundle.\n发行包不完整或已更改，请重新解压可信的发行包。", parent=root)
        root.destroy()
        return
    selected_language = language()
    def tr(key):
        return translate(key, selected_language)
    python = folder / (".venv/Scripts/pythonw.exe" if os.name == "nt" else ".venv/bin/python")
    if sys.version_info < (3, 11):
        messagebox.showerror("Releasecraft", tr("install.python"))
        root.destroy()
        return

    def launch():
        subprocess.Popen([str(python), "-m", "releasecraft.desktop", *sys.argv[1:]], cwd=folder, shell=False)
        root.destroy()

    if python.is_file():
        launch()
        return
    if (folder / ".venv").exists():
        messagebox.showerror("Releasecraft", tr("install.existing"))
        root.destroy()
        return
    root.resizable(False, False)
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    choice = tk.StringVar(value="中文" if selected_language == "zh" else "English")
    selector = ttk.Combobox(frame, textvariable=choice, values=("English", "中文"), state="readonly", width=9)
    selector.pack(anchor="e")
    welcome = ttk.Label(frame, font=("Segoe UI", 16, "bold"))
    welcome.pack(anchor="w")
    help_text = ttk.Label(frame, wraplength=490)
    help_text.pack(anchor="w", pady=15)
    status = tk.StringVar()
    ttk.Label(frame, textvariable=status).pack(anchor="w")
    bar = ttk.Progressbar(frame, mode="indeterminate")
    bar.pack(fill="x", pady=10)
    result = queue.Queue(maxsize=1)
    running = False
    failed = False

    def refresh(event=None):
        nonlocal selected_language
        selected_language = "zh" if choice.get() == "中文" else "en"
        if event is not None:
            try:
                save_language(selected_language)
            except (OSError, ReleaseError):
                pass
        root.title(tr("install.title"))
        welcome.configure(text=tr("install.welcome"))
        help_text.configure(text=tr("install.help"))
        button.configure(text=tr("install.button"))
        status.set(tr("install.running" if running else "install.failed" if failed else "install.ready"))
        root.update_idletasks()
        root.geometry(f"{max(510, root.winfo_reqwidth())}x{root.winfo_reqheight()}")

    def install():
        nonlocal running
        if running:
            return
        running = True
        button.state(["disabled"])
        bar.start()
        refresh()
        def worker():
            executable = Path(sys.executable)
            if os.name == "nt":
                executable = executable.with_name("python.exe")
            try:
                completed = subprocess.run([str(executable), str(folder / "install.py")], cwd=folder, capture_output=True, timeout=180,
                                           creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
                result.put(completed.returncode == 0)
            except (OSError, subprocess.TimeoutExpired):
                result.put(False)
        threading.Thread(target=worker, daemon=False).start()

    def poll():
        nonlocal running, failed
        try:
            success = result.get_nowait()
        except queue.Empty:
            root.after(100, poll)
            return
        running = False
        bar.stop()
        if success and python.is_file():
            launch()
        else:
            failed = True
            refresh()
            messagebox.showerror("Releasecraft", tr("install.failure_help"), parent=root)

    button = ttk.Button(frame, command=install)
    button.pack(anchor="e")
    selector.bind("<<ComboboxSelected>>", refresh)
    refresh()
    root.protocol("WM_DELETE_WINDOW", lambda: messagebox.showinfo("Releasecraft", tr("install.wait"), parent=root) if running else root.destroy())
    root.after(100, poll)
    root.deiconify()
    root.mainloop()


if __name__ == "__main__":
    main()
