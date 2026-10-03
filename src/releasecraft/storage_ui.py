"""Bilingual, nonblocking private-storage controls for the native desktop."""
from pathlib import Path
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from .managed import state_directory
from .storage import storage_status, clean_storage, export_audit


class StorageWindow:
    def __init__(self, app):
        self.app = app
        self.state = app.state_directory or state_directory()
        self.window = tk.Toplevel(app.root)
        self.window.geometry('790x450')
        self.window.minsize(640, 350)
        self.window.protocol('WM_DELETE_WINDOW', self.close)
        self.busy = False
        self.closed = False
        self.queue = queue.Queue(maxsize=1)
        self.data = None
        self.last_message = None
        self.localized = []
        self.info = ttk.Label(self.window, wraplength=740, padding=12)
        self.info.pack(fill='x')
        self.usage = ttk.Label(self.window, padding=(12, 0))
        self.usage.pack(fill='x')
        frame = ttk.Frame(self.window, padding=12)
        frame.pack(fill='both', expand=True)
        self.table = ttk.Treeview(frame, columns=('id','status','bytes','cleanup'), show='headings', selectmode='browse', height=8)
        for name, width in [('id',220),('status',140),('bytes',100),('cleanup',150)]:
            self.table.column(name, width=width, minwidth=70)
        scroll = ttk.Scrollbar(frame, orient='vertical', command=self.table.yview)
        self.table.configure(yscrollcommand=scroll.set)
        scroll.pack(side='right', fill='y')
        self.table.pack(fill='both', expand=True)
        self.message = ttk.Label(self.window, wraplength=740, padding=(12,4))
        self.message.pack(fill='x')
        buttons = ttk.Frame(self.window, padding=12)
        buttons.pack(fill='x')
        self.buttons = []
        for key, command in [('storage.refresh',self.refresh),('storage.export',self.export),('storage.clean',self.clean),('storage.clear',self.clear)]:
            widget=ttk.Button(buttons, command=command)
            widget.pack(side='left', padx=(0,6))
            self.localized.append((widget,key))
            self.buttons.append(widget)
        close=ttk.Button(buttons,command=self.close)
        close.pack(side='right')
        self.localized.append((close,'close'))
        self.refresh_language()
        self.timer=self.window.after(70,self.poll)
        self.refresh()

    def tr(self,key,**values):
        return self.app.tr(key,**values)

    def refresh_language(self):
        self.window.title(self.tr('storage.title'))
        self.info.configure(text=self.tr('storage.help'))
        for widget,key in self.localized:
            widget.configure(text=self.tr(key))
        for column in ('id','status','bytes','cleanup'):
            self.table.heading(column,text=self.tr('storage.'+column))
        self.render()
        self.window.update_idletasks()
        width=max(790,self.window.winfo_reqwidth())
        height=max(450,self.window.winfo_reqheight())
        self.window.geometry(f'{width}x{height}')

    def render(self):
        self.message.configure(text=self.tr('storage.working') if self.busy else self.tr(self.last_message or 'storage.unknown'))
        if not self.data or self.data.get('status')=='UNAVAILABLE':
            self.usage.configure(text=self.tr('storage.unavailable') if self.data else '')
            return
        self.usage.configure(text=self.tr('storage.usage',bytes=self.data['bytes'],limit=self.data['limit_bytes'] if self.data['limit_bytes'] is not None else self.tr('storage.available_space'),entries=self.data['entries']))
        selected=self.table.selection()
        self.table.delete(*self.table.get_children())
        for row in self.data['jobs']:
            status=row['status']
            key='storage.state.'+status
            status=self.tr(key) if status in ('RUNNING','INTERRUPTED','CANDIDATE','BLOCKED','FAILED','CANCELLED') else status
            detail=self.tr('storage.retained' if row.get('cleanup')=='RETAINED' else 'storage.audit' if row.get('retained') else 'storage.expired')
            self.table.insert('', 'end', iid=row['id'],values=(row['id'],status,row.get('audit_bytes',0),detail))
        if selected and self.table.exists(selected[0]):
            self.table.selection_set(selected[0])

    def run(self, action, message):
        if self.busy or self.closed:
            return
        self.busy=True
        for button in self.buttons:button.state(['disabled'])
        self.render()
        def worker():
            try:
                result=action()
                self.queue.put((result,message))
            except Exception:
                self.queue.put(({'status':'UNAVAILABLE','jobs':[]},'storage.unavailable'))
        threading.Thread(target=worker,daemon=False).start()

    def refresh(self):
        self.run(lambda:storage_status(self.state),'storage.unknown')

    def clean(self):
        self.run(lambda:clean_storage(self.state),'storage.cleaned')

    def clear(self):
        if self.busy:return
        if messagebox.askyesno(self.tr('storage.title'),self.tr('storage.confirm'),parent=self.window):
            self.run(lambda:clean_storage(self.state,True),'storage.cleared')

    def export(self):
        selected=self.table.selection()
        if not selected or self.busy:return
        destination=filedialog.asksaveasfilename(parent=self.window,title=self.tr('storage.export'),defaultextension='.zip',filetypes=[('ZIP','*.zip')])
        if not destination:return
        def action():
            export_audit(self.state,selected[0],Path(destination))
            return storage_status(self.state)
        self.run(action,'storage.exported')

    def poll(self):
        try:
            self.data,self.last_message=self.queue.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy=False
            for button in self.buttons:button.state(['!disabled'])
            self.render()
        if not self.closed:self.timer=self.window.after(70,self.poll)

    def close(self):
        if self.busy:
            self.message.configure(text=self.tr('storage.wait'))
            return
        self.closed=True
        self.window.after_cancel(self.timer)
        self.window.destroy()
