"""Settings window."""
import os, tkinter as tk
from tkinter import filedialog, messagebox
import customtkinter as ctk
import theme
from theme import THEME, FONT
from engine import IS_WIN, APP_VERSION, data_dir, is_admin, list_drives
import shell


class SettingsWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app, fg_color=THEME["bg"])
        self.app, self.s = app, app.settings
        self.title("FindIt settings")
        self.geometry("780x700")
        self.minsize(640, 520)
        self.transient(app)
        self.after(150, lambda: theme.win11_titlebar(self))
        tv = ctk.CTkTabview(self, fg_color=THEME["card"], segmented_button_selected_color=THEME["accent"],
                            segmented_button_unselected_color=THEME["card"], text_color=THEME["text"],
                            segmented_button_fg_color=THEME["stroke"])
        tv.pack(fill="both", expand=True, padx=16, pady=16)
        self.tabs = {}
        for name in ("General", "Indexing", "Windows", "Data"):
            t = tv.add(name)
            sc = ctk.CTkScrollableFrame(t, fg_color="transparent")
            sc.pack(fill="both", expand=True)
            sc.grid_columnconfigure(1, weight=1)
            self.tabs[name] = sc
        self._general(self.tabs["General"])
        self._indexing(self.tabs["Indexing"])
        self._windows(self.tabs["Windows"])
        self._data(self.tabs["Data"])

    # ---- small helpers
    def _title(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=(FONT, 14, "bold"), text_color=THEME["text"], anchor="w"
                     ).pack(fill="x", pady=(14, 4), padx=4)

    def _note(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=(FONT, 12), text_color=THEME["sub"], anchor="w", justify="left",
                     wraplength=620).pack(fill="x", padx=4, pady=(0, 4))

    def _switch(self, parent, text, key, cmd=None, state="normal"):
        var = tk.BooleanVar(value=bool(self.s[key]))
        def on():
            self.s[key] = var.get()
            self.s.save()
            if cmd:
                cmd()
        sw = ctk.CTkSwitch(parent, text=text, variable=var, command=on, font=(FONT, 13), text_color=THEME["text"],
                           progress_color=THEME["accent"], state=state)
        sw.pack(anchor="w", padx=8, pady=4)
        return var

    def _menu(self, parent, label, values, current, cmd):
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", pady=4, padx=4)
        ctk.CTkLabel(row, text=label, font=(FONT, 13), text_color=THEME["text"], width=210, anchor="w").pack(side="left")
        m = ctk.CTkOptionMenu(row, values=values, command=cmd, width=220, font=(FONT, 12),
                              fg_color=THEME["bg"], button_color=THEME["stroke"], text_color=THEME["text"])
        m.set(current)
        m.pack(side="left")

    def _button(self, parent, text, cmd, danger=False):
        b = ctk.CTkButton(parent, text=text, command=cmd, height=34, font=(FONT, 12),
                          fg_color=THEME["danger"] if danger else THEME["bg"],
                          hover_color="#A52318" if danger else THEME["stroke"],
                          text_color="white" if danger else THEME["text"], border_width=1, border_color=THEME["stroke"])
        b.pack(anchor="w", padx=8, pady=4)
        return b

    # ---- General
    def _general(self, p):
        a = self.app
        self._title(p, "Appearance")
        names = {"system": "System", "light": "Light", "dark": "Dark"}
        self._menu(p, "Theme", list(names.values()), names.get(self.s["theme"], "System"),
                   lambda v: a.apply_theme(v.lower()))
        views = {"details": "Details list", "small": "Small thumbnails", "medium": "Medium thumbnails",
                 "large": "Large thumbnails", "xlarge": "Extra large thumbnails"}
        self._menu(p, "Default view", list(views.values()), views.get(self.s["view"], "Details list"),
                   lambda v: a.set_view({x: k for k, x in views.items()}[v]))
        self._switch(p, "Show preview pane", "preview", lambda: a.set_preview(self.s["preview"]))
        self._switch(p, "Show side panel (bookmarks, history, drives)", "sidebar", lambda: a.set_sidebar(self.s["sidebar"]))
        self._title(p, "Searching")
        self._menu(p, "Double-click opens", ["The file", "Its folder"],
                   "The file" if self.s["double_click"] == "open" else "Its folder",
                   lambda v: self._set("double_click", "open" if v == "The file" else "folder"))
        self._menu(p, "Maximum results shown", ["1,000", "5,000", "20,000", "100,000"], f"{self.s['result_limit']:,}",
                   lambda v: (self._set("result_limit", int(v.replace(",", ""))), a._run_search()))
        pol = {"auto": "Automatic (recommended)", "always": "Every time FindIt starts", "stale": "Only when the saved index is old",
               "never": "Never (manual with F5)"}
        self._menu(p, "Refresh index at startup", list(pol.values()), pol.get(self.s["rescan"], pol["auto"]),
                   lambda v: self._set("rescan", {x: k for k, x in pol.items()}[v]))
        self._note(p, "Automatic: with administrator mode on NTFS drives FindIt re-reads the whole PC in seconds every start. "
                      "Otherwise it uses the saved index and refreshes only when it is more than 12 hours old, "
                      "while Live updates keeps it current.")

    def _set(self, k, v):
        self.s[k] = v
        self.s.save()

    # ---- Indexing
    def _indexing(self, p):
        a = self.app
        self._title(p, "Speed")
        self.mode_lbl = ctk.CTkLabel(p, text="", font=(FONT, 12), text_color=THEME["sub"], anchor="w",
                                     justify="left", wraplength=620)
        self.mode_lbl.pack(fill="x", padx=4)
        self._update_mode()
        self._title(p, "Drives")
        for d in list_drives():
            var = tk.BooleanVar(value=d["letter"].upper() not in {x.upper() for x in self.s["skip_drives"]})
            def tog(var=var, L=d["letter"]):
                sk = [x for x in self.s["skip_drives"] if x.upper() != L.upper()]
                if not var.get():
                    sk.append(L)
                self._set("skip_drives", sk)
            ctk.CTkSwitch(p, text=f"{d['root']}  {d['label'] or ''}  ({d['kind']})", variable=var, command=tog,
                          font=(FONT, 13), text_color=THEME["text"], progress_color=THEME["accent"]).pack(anchor="w", padx=8, pady=3)
        self._switch(p, "Include removable drives (USB, SD cards)", "index_removable")
        self._switch(p, "Automatically index a drive when it is plugged in", "auto_new_drives")
        self._switch(p, "Skip hidden and system files", "skip_hidden")

        self._title(p, "Extra locations (network folders, other folders)")
        self.extra_box = ctk.CTkFrame(p, fg_color="transparent", height=1)
        self.extra_box.pack(fill="x")
        self._button(p, "Add folder or drive…", self._add_extra)

        self._title(p, "Exceptions: never index these")
        self._note(p, "Folders (full path, or just a name like node_modules that is skipped everywhere):")
        self.exd_box = ctk.CTkFrame(p, fg_color="transparent", height=1)
        self.exd_box.pack(fill="x")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=4)
        self.exd_entry = ctk.CTkEntry(row, placeholder_text="folder name or path", width=260)
        self.exd_entry.pack(side="left")
        ctk.CTkButton(row, text="Add", width=60, command=self._add_exd, fg_color=THEME["accent"]).pack(side="left", padx=6)
        ctk.CTkButton(row, text="Browse…", width=80, command=self._browse_exd, fg_color=THEME["bg"],
                      text_color=THEME["text"], hover_color=THEME["stroke"], border_width=1, border_color=THEME["stroke"]).pack(side="left")
        self._note(p, "File extensions to leave out (comma separated, e.g. tmp, log, bak):")
        self.exe_entry = ctk.CTkEntry(p, width=360)
        self.exe_entry.insert(0, ", ".join(self.s["exclude_ext"]))
        self.exe_entry.pack(anchor="w", padx=8, pady=4)
        self.exe_entry.bind("<FocusOut>", lambda e: self._save_exe())
        self.exe_entry.bind("<Return>", lambda e: self._save_exe())

        self._title(p, "My file types (new extensions)")
        self._note(p, "Create your own filter button, for example  Ebooks = epub, mobi, azw3")
        self.types_box = ctk.CTkFrame(p, fg_color="transparent", height=1)
        self.types_box.pack(fill="x")
        row = ctk.CTkFrame(p, fg_color="transparent")
        row.pack(fill="x", padx=4, pady=4)
        self.t_name = ctk.CTkEntry(row, placeholder_text="Name (Ebooks)", width=150)
        self.t_name.pack(side="left")
        self.t_ext = ctk.CTkEntry(row, placeholder_text="epub, mobi, azw3", width=220)
        self.t_ext.pack(side="left", padx=6)
        ctk.CTkButton(row, text="Add type", width=80, command=self._add_type, fg_color=THEME["accent"]).pack(side="left")
        self._title(p, "Apply")
        self._note(p, "Changes to drives, locations and exceptions take effect after rebuilding the index.")
        self._button(p, "Rebuild index now", a.reindex)
        self._refresh_lists()

    def _update_mode(self):
        if not IS_WIN:
            t = "Instant NTFS mode is available on Windows. Using the fast multi-threaded scanner."
        elif self.app.index.mode == "ntfs":
            t = "⚡ Instant NTFS mode is ON: the whole PC is read from the NTFS file table in seconds."
        elif is_admin():
            t = "Administrator mode is on. Non-NTFS drives (USB, network) use the fast multi-threaded scanner."
        else:
            t = ("Standard mode (multi-threaded scanner). For instant indexing like Everything, turn on "
                 "'Run as administrator' in the Windows tab.")
        self.mode_lbl.configure(text=t)

    def _rows(self, box, items, remove, fmt=lambda x: x):
        for w in box.winfo_children():
            w.destroy()
        for it in items:
            r = ctk.CTkFrame(box, fg_color=THEME["bg"], corner_radius=6)
            r.pack(fill="x", padx=8, pady=2)
            ctk.CTkLabel(r, text=fmt(it), font=(FONT, 12), text_color=THEME["text"], anchor="w").pack(side="left", padx=8, pady=4)
            ctk.CTkButton(r, text="✕", width=28, height=24, fg_color="transparent", hover_color=THEME["stroke"],
                          text_color=THEME["text"], command=lambda it=it: remove(it)).pack(side="right", padx=4)

    def _refresh_lists(self):
        self._rows(self.extra_box, self.s["extra_locations"], self._rm_extra)
        self._rows(self.exd_box, self.s["exclude_dirs"], self._rm_exd)
        self._rows(self.types_box, list(self.s["custom_types"].items()), self._rm_type,
                   lambda kv: f"{kv[0]}:  {', '.join(kv[1])}")

    def _add_extra(self):
        d = filedialog.askdirectory(parent=self, title="Choose a folder or drive to index")
        if d:
            d = os.path.normpath(d)
            if d not in self.s["extra_locations"]:
                self.s["extra_locations"] = self.s["extra_locations"] + [d]
                self.s.save()
                self.app.index_location(d)
            self._refresh_lists()

    def _rm_extra(self, d):
        self._set("extra_locations", [x for x in self.s["extra_locations"] if x != d])
        self.app.index.drop_prefix(d)
        self.app._run_search()
        self._refresh_lists()

    def _add_exd(self):
        v = self.exd_entry.get().strip()
        if v and v not in self.s["exclude_dirs"]:
            self._set("exclude_dirs", self.s["exclude_dirs"] + [v])
            self.app.index.configure()
        self.exd_entry.delete(0, "end")
        self._refresh_lists()

    def _browse_exd(self):
        d = filedialog.askdirectory(parent=self, title="Choose a folder to skip")
        if d:
            self.exd_entry.delete(0, "end")
            self.exd_entry.insert(0, os.path.normpath(d))
            self._add_exd()

    def _rm_exd(self, d):
        self._set("exclude_dirs", [x for x in self.s["exclude_dirs"] if x != d])
        self.app.index.configure()
        self._refresh_lists()

    def _save_exe(self):
        exts = [e.strip().lstrip(".").lower() for e in self.exe_entry.get().replace(";", ",").split(",") if e.strip()]
        self._set("exclude_ext", exts)
        self.app.index.configure()

    def _add_type(self):
        n, e = self.t_name.get().strip(), self.t_ext.get().replace(";", ",")
        exts = [x.strip().lstrip(".").lower() for x in e.split(",") if x.strip()]
        if n and exts and n not in ("All", "Folders"):
            ct = dict(self.s["custom_types"])
            ct[n] = exts
            self._set("custom_types", ct)
            self.t_name.delete(0, "end")
            self.t_ext.delete(0, "end")
            self.app.refresh_categories()
            self._refresh_lists()

    def _rm_type(self, kv):
        ct = {k: v for k, v in self.s["custom_types"].items() if k != kv[0]}
        self._set("custom_types", ct)
        self.app.refresh_categories()
        self._refresh_lists()

    # ---- Windows
    def _windows(self, p):
        a = self.app
        if not IS_WIN:
            self._note(p, "These options are for Windows. You can still preview them here.")
        st = "normal" if IS_WIN else "disabled"
        self._title(p, "Windows Explorer")
        var = tk.BooleanVar(value=shell.context_menu_installed())
        def ctx():
            try:
                shell.install_context_menu() if var.get() else shell.remove_context_menu()
            except Exception as e:
                messagebox.showerror("FindIt", f"Could not change the right-click menu:\n{e}", parent=self)
                var.set(not var.get())
        ctk.CTkSwitch(p, text="Add “Search with FindIt” to the right-click menu of folders and drives", variable=var,
                      command=ctx, font=(FONT, 13), text_color=THEME["text"], progress_color=THEME["accent"],
                      state=st).pack(anchor="w", padx=8, pady=4)
        self._title(p, "Startup")
        self._switch(p, "Start FindIt when I sign in to Windows", "start_with_windows", self._apply_startup, st)
        self._switch(p, "Start minimized to the tray", "start_minimized", self._apply_startup, st)
        self._title(p, "Speed (administrator)")
        def adm():
            if self.s["admin"] and not is_admin():
                if messagebox.askyesno("FindIt", "FindIt needs to restart to get administrator rights.\nRestart now?", parent=self):
                    if shell.relaunch_as_admin(["--elevated"]):
                        a._quit()
                        return
                self.s["admin"] = False
                self.s.save()
            self._apply_startup()
        self._switch(p, "Run as administrator for instant NTFS indexing (Windows asks permission each time)", "admin", adm, st)
        self._note(p, "With 'Start FindIt when I sign in' + administrator, FindIt starts through Task Scheduler "
                      "and Windows does not ask each time.")
        self._title(p, "Notification area and Action Center")
        self._switch(p, "Show FindIt in the notification area (system tray)", "tray", a.apply_tray, st)
        self._switch(p, "Closing the window keeps FindIt running in the tray", "close_to_tray", None, st)
        self._switch(p, "Show notifications in Action Center (index ready, new drive, duplicates removed)", "notify", None, st)
        self._switch(p, "Open FindIt anywhere with Ctrl + Alt + Space", "hotkey", a.apply_hotkey, st)

    def _apply_startup(self):
        if IS_WIN:
            shell.set_startup(self.s["start_with_windows"], self.s["admin"], self.s["start_minimized"])

    # ---- Data
    def _data(self, p):
        a = self.app
        self._title(p, "Index")
        self.stat_lbl = ctk.CTkLabel(p, text="", font=(FONT, 12), text_color=THEME["sub"], anchor="w", justify="left")
        self.stat_lbl.pack(fill="x", padx=4)
        self._update_stats()
        self._button(p, "Clear saved index (rebuilds at next start)", lambda: (a.index.clear_cache(), self._update_stats()))
        self._title(p, "Backup, import and export")
        self._note(p, "Backup contains settings, bookmarks, saved searches and history.")
        self._button(p, "Export backup…", a.export_backup)
        self._button(p, "Import backup or list of paths…", a.import_backup)
        self._button(p, "Export current results…", a.export_results)
        self._title(p, "Privacy")
        self._button(p, "Clear search history", lambda: (self._set("history", []), a.refresh_sidebar()))
        self._button(p, "Open settings folder", lambda: shell.open_path(data_dir()))
        self._title(p, "About")
        self._note(p, f"FindIt {APP_VERSION}. Instant file search. Settings are stored in {data_dir()}")

    def _update_stats(self):
        ix = self.app.index
        try:
            size = os.path.getsize(ix.cache_path) / (1 << 20)
        except OSError:
            size = 0
        self.stat_lbl.configure(text=f"{len(ix):,} items indexed · saved index {size:.1f} MB · mode: {ix.mode}")
