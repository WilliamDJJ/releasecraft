"""A local review surface over frozen core evidence, with explicit policy export."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from tkinter import font as tkfont

from .policy import load_policy
from .review import review_policy, decide
from .safety import ReleaseError, canonical, read_safe, separate


class ReviewWindow:
    def __init__(self, app):
        from .desktop import safe_label
        self.app = app
        self.plan = json.loads(read_safe(Path(app.result['audit']), 'plan.json')[0])
        self.policy = review_policy(self.plan)
        self.window = tk.Toplevel(app.root)
        self.window.title(app.tr('review.title'))
        self.window.geometry('960x560')
        self.window.minsize(760, 440)
        self.localized = []
        self.pending = {}
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        self.widget(ttk.Label, frame, 'review.help', wraplength=900).pack(anchor='w', pady=(0, 8))
        table_frame = ttk.Frame(frame)
        table_frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(table_frame, columns=('path', 'state', 'reason', 'size'), show='headings', selectmode='extended')
        state_width = max(160, tkfont.nametofont('TkDefaultFont').measure('Pending: Needs review') + 24)
        for column, width in [('path', 380), ('state', state_width), ('reason', 330), ('size', 100)]:
            self.table.column(column, width=width, minwidth=width, stretch=False)
        horizontal = ttk.Scrollbar(table_frame, orient='horizontal', command=self.table.xview)
        horizontal.pack(side='bottom', fill='x')
        scroll = ttk.Scrollbar(table_frame, orient='vertical', command=self.table.yview)
        scroll.pack(side='right', fill='y')
        self.table.configure(yscrollcommand=scroll.set, xscrollcommand=horizontal.set)
        self.table.pack(fill='both', expand=True)
        self.rows = {str(i): row for i, row in enumerate(self.plan['files'])}
        for key, row in self.rows.items():
            self.table.insert('', 'end', iid=key, values=(safe_label(row['path']), row['state'], row['reason'], row['size']))
        lower = ttk.Frame(frame)
        lower.pack(fill='x', pady=8)
        self.widget(ttk.Label, lower, 'review.reason').pack(side='left')
        self.reason = tk.StringVar()
        ttk.Entry(lower, textvariable=self.reason).pack(side='left', fill='x', expand=True, padx=8)
        buttons = ttk.Frame(frame)
        buttons.pack(fill='x')
        for action in ('include', 'exclude', 'review'):
            self.widget(ttk.Button, buttons, 'review.' + action, command=lambda a=action: self.apply(a)).pack(side='left', padx=(0, 6))
        self.widget(ttk.Button, buttons, 'review.save', command=self.save).pack(side='right')
        self.refresh_language()

    def widget(self, kind, parent, key, **kwargs):
        widget = kind(parent, text=self.app.tr(key), **kwargs)
        self.localized.append((widget, key))
        return widget

    def refresh_language(self):
        self.window.title(self.app.tr('review.title'))
        for widget, key in self.localized:
            widget.configure(text=self.app.tr(key))
        for name in ('path', 'state', 'reason', 'size'):
            self.table.heading(name, text=self.app.tr('review.' + name))
        for key, action in self.pending.items():
            self.table.set(key, 'state', self.app.tr('review.pending') + ': ' + self.app.tr('review.' + action))

    def apply(self, action):
        if self.app.busy:
            return
        try:
            updated = self.policy
            for key in self.table.selection():
                updated = decide(self.plan, updated, self.rows[key]['path'], action, self.reason.get().strip())
            self.policy = updated
            for key in self.table.selection():
                self.pending[key] = action
            self.refresh_language()
        except (ReleaseError, ValueError):
            messagebox.showerror(self.app.tr('review.title'), self.app.tr('review.rejected'), parent=self.window)

    def save(self):
        if self.app.busy:
            return
        name = filedialog.asksaveasfilename(parent=self.window, title=self.app.tr('review.save'),
                                           initialfile='releasecraft-policy.json', defaultextension='.json',
                                           filetypes=[(self.app.tr('json_policy'), '*.json')])
        if not name:
            return
        try:
            separate(self.app.source.get(), name)
            blob = canonical(load_policy(value=self.policy))
            with Path(name).open('xb') as stream:
                stream.write(blob)
            self.app.policy_path.set(name)
            messagebox.showinfo(self.app.tr('review.title'), self.app.tr('review.saved'), parent=self.window)
        except (OSError, ReleaseError, ValueError):
            messagebox.showerror(self.app.tr('review.title'), self.app.tr('review.save_error'), parent=self.window)
