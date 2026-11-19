"""FindIt main window (started by findit.py)."""
import os, sys, re, csv, json, time, queue, zipfile, argparse, threading, tkinter as tk
from tkinter import filedialog, messagebox, simpledialog
import customtkinter as ctk

import theme
from theme import THEME, FONT
from engine import (highlight_terms, Settings, Index, Watcher, IS_WIN, data_dir, resource_path, all_categories,
                    human_size, human_date, type_name, is_admin, IMG_EXT, TEXT_EXT)
from thumbs import THUMB_EXT, get_thumbnail
import shell
import ipc
from views import VirtualDetails, ThumbView, LiteScroll

SORTS = [("Name", "name"), ("Location", "path"), ("Size", "size"), ("Type", "type"),
         ("Date modified", "date"), ("Date created / added", "created")]
SORT_LABEL = {k: v for v, k in SORTS}
THUMB = {"small": 64, "medium": 96, "large": 160, "xlarge": 256}
VIEWS = [("details", "Details list"), ("small", "Small thumbnails"), ("medium", "Medium thumbnails"),
         ("large", "Large thumbnails"), ("xlarge", "Extra large thumbnails")]
GLASS_NAMES = {"off": "Off", "acrylic": "Acrylic (frosted glass)", "mica": "Mica (soft tint)"}
QUICK = [("🕒  Modified today", "dm:today"), ("📅  Modified last 7 days", "dm:week"),
         ("🆕  Created this week", "dc:thisweek"), ("📦  Large files (over 500 MB)", "size:>500mb"),
         ("🖼  Pictures from this month", "type:pictures dm:thismonth"), ("🗂  Empty files", "size:empty")]


def clip(s, n):
    return s if len(s) <= n else s[: n - 1] + "…"


class App(ctk.CTk):
    def __init__(self, args, settings):
        ctk.set_appearance_mode(settings["theme"])
        ctk.set_default_color_theme("blue")
        super().__init__(fg_color=theme.root_bg(settings))
        self.args, self.settings = args, settings
        self.title("FindIt")
        geo = settings["geometry"]
        self.geometry(geo if re.fullmatch(r"\d+x\d+(\+-?\d+\+-?\d+)?", geo or "") else "1360x780")
        self.minsize(900, 540)
        ico = resource_path("findit.ico")
        if IS_WIN and os.path.exists(ico):
            try:
                self.iconbitmap(ico)
            except Exception:
                pass
        self.cats = all_categories(settings["custom_types"])
        self.index = Index(os.path.join(data_dir(), "index.cache"), settings)
        self.watcher = Watcher(self.index)
        self.tray = shell.Tray([("Show FindIt", lambda: self.ui(self.show_window)),
                                ("Find duplicate files…", lambda: self.ui(self.open_duplicates)),
                                ("Rebuild index", lambda: self.ui(self.reindex)),
                                ("-", None),
                                ("Exit", lambda: self.ui(self._quit))])
        self.hotkey = shell.Hotkey(lambda: self.ui(self.show_window))
        self.ipc = ipc.Server(lambda msg: self.ui(lambda: self._ipc(msg)))
        self.highlight = []
        self.seq, self.after_id, self.sel_id, self.hist_id = 0, None, None, None
        self._uiq = queue.Queue()
        self._pump()
        self.sort_key, self.sort_rev = settings["sort_key"], settings["sort_rev"]
        self.category = "All"
        self.scope = [os.path.normpath(args.path)] if args.path and os.path.isdir(args.path) else []
        self.results, self.total, self.error = [], 0, None
        self.view = None
        self.view_mode = settings["view"]
        self.preview_on = settings["preview"]
        self._thumb = None
        self._poll_n = 0
        self.dup_win = self.settings_win = None
        self.opt_case, self.opt_regex = tk.BooleanVar(), tk.BooleanVar()
        self.opt_path = tk.BooleanVar()
        self.opt_live = tk.BooleanVar(value=settings["live"])
        self.tabs = [self._blank_tab()]
        self.tabs[0]["scope"] = list(self.scope)
        self.cur = 0

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self._build_sidebar()
        self._build_main()
        self.set_view(self.view_mode, rebuild_only=True)
        self.refresh_sidebar()
        self._rebuild_tabs()
        self._update_scope_chip()
        self._bind_keys()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.set_sidebar(settings["sidebar"])
        self.set_preview(self.preview_on)
        self.update_idletasks()
        self.apply_glass()
        self.after(30, self._late_init)      # window is on screen first, heavy work after

    def _late_init(self):
        self._startup()
        self.ipc.start()
        self.apply_tray()
        self.apply_hotkey()
        self.after(1000, self._poll)
        if self.args.background and self.tray.icon:
            self.after(300, self.withdraw)
        self.after(1500, self._first_run)

    def apply_glass(self):
        mode = self.settings["glass"] if IS_WIN else "off"
        on = theme.apply_glass(self, mode, self.settings["opacity"]) if IS_WIN else False
        if not on:
            theme.win11_titlebar(self)
            self.configure(fg_color=THEME["bg"])

    def _ipc(self, msg):
        """another FindIt launch (right-click menu etc.) handed its request to this window"""
        if msg.get("background"):
            return
        self.show_window()
        p = msg.get("path")
        if p and os.path.isdir(p):
            if not self.entry.get().strip() and not self.scope:
                self.set_scope([p])
            else:
                self.new_tab(scope=[p])

    # ---- background threads never touch Tk: they post work here, the main thread runs it
    def ui(self, fn):
        self._uiq.put(fn)

    def _pump(self):
        for _ in range(60):
            try:
                fn = self._uiq.get_nowait()
            except queue.Empty:
                break
            try:
                fn()
            except Exception:
                pass
        self.after(40, self._pump)

    # =====================================================================  layout
    def _round_btn(self, parent, text, cmd, tip=None):
        return ctk.CTkButton(parent, text=text, width=44, height=44, corner_radius=22, fg_color=THEME["card"],
                             hover_color=THEME["hover"], text_color=THEME["text"], border_width=1,
                             border_color=THEME["stroke"], font=(FONT, 16), command=cmd)

    def _build_sidebar(self):
        self.side_panel = ctk.CTkFrame(self, width=232, **theme.panel_kw())
        self.side_panel.grid(row=0, column=0, sticky="nsw", padx=(12, 0), pady=12)
        self.side_panel.grid_propagate(False)
        self.side_panel.grid_rowconfigure(0, weight=1)
        self.side_panel.grid_columnconfigure(0, weight=1)
        self.sidebar = LiteScroll(self.side_panel)
        self.sidebar.grid(row=0, column=0, sticky="nsew", padx=8, pady=10)

    def _build_main(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.grid(row=0, column=1, sticky="nsew")
        main.grid_columnconfigure(0, weight=1)
        main.grid_rowconfigure(3, weight=1)
        self.main = main

        self.tabbar = ctk.CTkFrame(main, fg_color="transparent", height=36)
        self.tabbar.grid(row=0, column=0, sticky="ew", padx=16, pady=(12, 0))

        top = ctk.CTkFrame(main, fg_color="transparent")
        top.grid(row=1, column=0, sticky="ew", padx=16, pady=(8, 8))
        top.grid_columnconfigure(1, weight=1)
        self._round_btn(top, "☰", self.toggle_sidebar).grid(row=0, column=0, padx=(0, 8))
        self.entry = ctk.CTkEntry(top, height=44, corner_radius=22, border_width=1, fg_color=THEME["card"],
                                  border_color=THEME["stroke"], text_color=THEME["text"],
                                  placeholder_text="🔍  Search files and folders…   try  ext:pdf  size:>10mb  dm:today  !draft",
                                  font=(FONT, 14))
        self.entry.grid(row=0, column=1, sticky="ew")
        self.entry.bind("<KeyRelease>", self._key_release)
        self.entry.bind("<Return>", lambda e: (self._run_search(), self.settings.add_history(self.entry.get()), self.refresh_sidebar()))
        self.entry.bind("<Down>", lambda e: self.view.focus_first())
        self.tools_btn = self._round_btn(top, "⋯", self.tools_menu)
        self.tools_btn.grid(row=0, column=2, padx=(8, 0))
        self.view_btn = self._round_btn(top, "▦", self.view_menu)
        self.view_btn.grid(row=0, column=3, padx=(8, 0))
        self._round_btn(top, "◧", self.toggle_preview).grid(row=0, column=4, padx=(8, 0))
        self._round_btn(top, "⟳", self.reindex).grid(row=0, column=5, padx=(8, 0))
        self._round_btn(top, "◐", self.toggle_theme).grid(row=0, column=6, padx=(8, 0))
        self._round_btn(top, "⚙", self.open_settings).grid(row=0, column=7, padx=(8, 0))

        bar = ctk.CTkFrame(main, fg_color="transparent")
        bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 8))
        self.seg_holder = ctk.CTkFrame(bar, fg_color="transparent")
        self.seg_holder.pack(side="left")
        self.seg = None
        self.refresh_categories(run=False)
        self.scope_btn = ctk.CTkButton(bar, text="", height=32, corner_radius=16, fg_color=THEME["accent"],
                                       hover_color=THEME["accent_hover"], font=(FONT, 12), command=self.clear_scope, width=10)
        right = ctk.CTkFrame(bar, height=40, **theme.panel_kw(14))
        right.pack(side="right")
        pad = dict(pady=5)
        self.opt_btn = ctk.CTkButton(right, text="Options ▾", width=84, height=30, fg_color="transparent",
                                     hover_color=THEME["hover"], text_color=THEME["text"], font=(FONT, 12),
                                     command=self.options_menu)
        self.opt_btn.pack(side="right", padx=(2, 6), **pad)
        self.dir_btn = ctk.CTkButton(right, text="", width=34, height=30, fg_color="transparent",
                                     hover_color=THEME["hover"], text_color=THEME["text"], font=(FONT, 13),
                                     command=self.toggle_sort_dir)
        self.dir_btn.pack(side="right", **pad)
        self.sort_menu = ctk.CTkOptionMenu(right, values=[n for n, _ in SORTS], width=150, height=30,
                                           font=(FONT, 12), fg_color=THEME["hover"], button_color=THEME["hover"],
                                           button_hover_color=THEME["stroke"], text_color=THEME["text"],
                                           command=self._sort_menu_pick)
        self.sort_menu.pack(side="right", padx=4, **pad)
        ctk.CTkLabel(right, text="Sort by", font=(FONT, 12), text_color=THEME["sub"]).pack(side="right", padx=(12, 2), **pad)
        self._sync_sort_ui()

        body = ctk.CTkFrame(main, fg_color="transparent")
        body.grid(row=3, column=0, sticky="nsew", padx=16, pady=(0, 6))
        body.grid_columnconfigure(0, weight=1)
        body.grid_rowconfigure(0, weight=1)
        self.card = ctk.CTkFrame(body, **theme.panel_kw())
        self.card.grid(row=0, column=0, sticky="nsew")
        self.card.grid_columnconfigure(0, weight=1)
        self.card.grid_rowconfigure(0, weight=1)
        self._build_preview(body)

        pill = ctk.CTkFrame(main, height=28, **theme.panel_kw(14))
        pill.grid(row=4, column=0, sticky="w", padx=16, pady=(0, 12))
        self.status = ctk.CTkLabel(pill, text="Starting…", anchor="w", font=(FONT, 12), text_color=THEME["sub"])
        self.status.pack(padx=14, pady=3)

    def _build_preview(self, body):
        pf = ctk.CTkFrame(body, width=300, **theme.panel_kw())
        pf.grid_propagate(False)
        pf.grid_columnconfigure(0, weight=1)
        pf.grid_rowconfigure(3, weight=1)
        self.pf = pf
        self.p_icon = ctk.CTkLabel(pf, text="🔍", font=(FONT, 54), text_color=THEME["sub"])
        self.p_icon.grid(row=0, column=0, pady=(22, 8))
        self.p_thumb = ctk.CTkLabel(pf, text="")
        self.p_thumb.grid(row=0, column=0, pady=(14, 8))
        self.p_thumb.grid_remove()
        self.p_name = ctk.CTkLabel(pf, text="Select a file to preview", wraplength=262, font=(FONT, 14, "bold"),
                                   text_color=THEME["text"])
        self.p_name.grid(row=1, column=0, padx=16, pady=(0, 4))
        self.p_meta = ctk.CTkLabel(pf, text="", wraplength=262, justify="left", anchor="w", font=(FONT, 12),
                                   text_color=THEME["sub"])
        self.p_meta.grid(row=2, column=0, padx=16, sticky="w")
        self.p_text = ctk.CTkTextbox(pf, wrap="word", font=("Consolas" if IS_WIN else "Courier", 11),
                                     fg_color=THEME["bg"], text_color=THEME["text"], corner_radius=8)
        self.p_text.grid(row=3, column=0, padx=12, pady=12, sticky="nsew")
        self.p_text.grid_remove()

    def _bind_keys(self):
        b = self.bind
        b("<Control-f>", lambda e: (self.entry.focus_set(), self.entry.select_range(0, "end")))
        b("<Control-p>", lambda e: self.toggle_preview())
        b("<Control-t>", lambda e: self.new_tab())
        b("<Control-w>", lambda e: self.close_tab(self.cur))
        b("<Control-Tab>", lambda e: self.switch_tab((self.cur + 1) % len(self.tabs)))
        b("<Control-n>", lambda e: shell.new_window())
        b("<Control-b>", lambda e: self.toggle_sidebar())
        b("<Control-d>", lambda e: self.bookmark_selected())
        b("<Control-D>", lambda e: self.open_duplicates())
        b("<Control-comma>", lambda e: self.open_settings())
        b("<F5>", lambda e: self.reindex())
        b("<Escape>", lambda e: self._clear())

    # =====================================================================  categories / sorting
    def refresh_categories(self, run=True):
        self.cats = all_categories(self.settings["custom_types"])
        if self.seg is not None:
            self.seg.destroy()
        if self.category not in self.cats:
            self.category = "All"
        self.seg = ctk.CTkSegmentedButton(self.seg_holder, values=list(self.cats), command=self.set_category,
                                          font=(FONT, 12), corner_radius=14, height=34,
                                          selected_color=THEME["accent"], selected_hover_color=THEME["accent_hover"],
                                          unselected_color=THEME["card"], unselected_hover_color=THEME["hover"],
                                          text_color=THEME["text"], fg_color=THEME["card"], border_width=3)
        self.seg.set(self.category)
        self.seg.pack()
        if run:
            self._run_search()

    def _sync_sort_ui(self):
        self.sort_menu.set(SORT_LABEL.get(self.sort_key, "Name"))
        self.dir_btn.configure(text="▼" if self.sort_rev else "▲")
        if self.view:
            self.view.set_sort(self.sort_key, self.sort_rev)

    def sort_by(self, key):
        if key == self.sort_key:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_key = key
            self.sort_rev = key in ("size", "date", "created")
        self._after_sort()

    def _sort_menu_pick(self, label):
        key = dict(SORTS)[label]
        if key != self.sort_key:
            self.sort_key = key
            self.sort_rev = key in ("size", "date", "created")
        self._after_sort()

    def toggle_sort_dir(self):
        self.sort_rev = not self.sort_rev
        self._after_sort()

    def _after_sort(self):
        self.settings["sort_key"], self.settings["sort_rev"] = self.sort_key, self.sort_rev
        self.settings.save()
        self._sync_sort_ui()
        self._run_search()

    # =====================================================================  tabs
    def _blank_tab(self):
        return {"q": "", "category": "All", "case": False, "regex": False, "path": False, "scope": [],
                "sort_key": self.settings["sort_key"], "sort_rev": self.settings["sort_rev"], "title": "New tab"}

    def _save_tab(self):
        t = self.tabs[self.cur]
        t.update(q=self.entry.get(), category=self.category, case=self.opt_case.get(), regex=self.opt_regex.get(),
                 path=self.opt_path.get(), scope=list(self.scope), sort_key=self.sort_key, sort_rev=self.sort_rev)

    def _load_tab(self):
        t = self.tabs[self.cur]
        self.entry.delete(0, "end")
        if t["q"]:
            self.entry.insert(0, t["q"])
        self.category = t["category"] if t["category"] in self.cats else "All"
        self.seg.set(self.category)
        self.opt_case.set(t["case"]); self.opt_regex.set(t["regex"]); self.opt_path.set(t["path"])
        self.scope = list(t["scope"])
        self.sort_key, self.sort_rev = t["sort_key"], t["sort_rev"]
        self._sync_sort_ui()
        self._update_scope_chip()
        self._rebuild_tabs()
        self._run_search()

    def new_tab(self, q="", scope=None):
        self._save_tab()
        t = self._blank_tab()
        t["q"], t["scope"] = q, list(scope or [])
        self.tabs.append(t)
        self.cur = len(self.tabs) - 1
        self._load_tab()
        self.entry.focus_set()

    def close_tab(self, i):
        if len(self.tabs) <= 1:
            return
        self._save_tab()
        del self.tabs[i]
        self.cur = min(self.cur if i >= self.cur else self.cur - 1, len(self.tabs) - 1)
        self.cur = max(self.cur, 0)
        self._load_tab()

    def switch_tab(self, i):
        if i == self.cur:
            return
        self._save_tab()
        self.cur = i
        self._load_tab()

    def _rebuild_tabs(self):
        for w in self.tabbar.winfo_children():
            w.destroy()
        for i, t in enumerate(self.tabs):
            on = i == self.cur
            fr = ctk.CTkFrame(self.tabbar, corner_radius=12, fg_color=THEME["card"] if on else THEME["hover"],
                              border_width=1, border_color=THEME["stroke"])
            fr.pack(side="left", padx=(0, 4))
            ctk.CTkButton(fr, text=clip(t["title"], 24), width=10, height=28, fg_color="transparent",
                          hover_color=THEME["hover"] if on else THEME["stroke"], text_color=THEME["text"] if on else THEME["sub"],
                          font=(FONT, 12), command=lambda i=i: self.switch_tab(i)).pack(side="left", padx=(4, 0))
            if len(self.tabs) > 1:
                ctk.CTkButton(fr, text="✕", width=22, height=22, fg_color="transparent", hover_color=THEME["stroke"],
                              text_color=THEME["sub"], font=(FONT, 11),
                              command=lambda i=i: self.close_tab(i)).pack(side="left", padx=(0, 4))
        ctk.CTkButton(self.tabbar, text="＋", width=32, height=30, corner_radius=12, fg_color=THEME["hover"],
                      hover_color=THEME["stroke"], text_color=THEME["text"], font=(FONT, 15),
                      command=self.new_tab).pack(side="left")

    def _tab_title(self):
        q = self.entry.get().strip()
        title = q or (os.path.basename(self.scope[0].rstrip("\\/")) or self.scope[0] if self.scope else
                      (self.category if self.category != "All" else "New tab"))
        t = self.tabs[self.cur]
        if t["title"] != title:
            t["title"] = title
            self._rebuild_tabs()

    # =====================================================================  scope
    def set_scope(self, folders):
        self.scope = [os.path.normpath(f) for f in folders]
        self._update_scope_chip()
        self._run_search()

    def clear_scope(self):
        self.set_scope([])

    def choose_scope(self):
        d = filedialog.askdirectory(parent=self, title="Search only inside this folder")
        if d:
            self.set_scope([d])

    def _update_scope_chip(self):
        if self.scope:
            name = os.path.basename(self.scope[0].rstrip("\\/")) or self.scope[0]
            self.scope_btn.configure(text=f"📂  {clip(name, 26)}   ✕")
            self.scope_btn.pack(side="left", padx=10)
        else:
            self.scope_btn.pack_forget()

    # =====================================================================  searching
    def set_category(self, v):
        self.category = v
        self._run_search()

    def _clear(self):
        self.entry.delete(0, "end")
        self._run_search()

    def _debounce(self):
        if self.after_id:
            self.after_cancel(self.after_id)
        self.after_id = self.after(110, self._run_search)

    def _key_release(self, e):
        if e.keysym in ("Return", "Down", "Up", "Tab", "Escape"):
            return
        self._debounce()
        if self.hist_id:
            self.after_cancel(self.hist_id)
        self.hist_id = self.after(2500, self._record_history)

    def _record_history(self):
        q = self.entry.get().strip()
        if len(q) >= 2:
            self.settings.add_history(q)
            self.refresh_sidebar()

    def _limit(self):
        lim = int(self.settings["result_limit"])
        return lim if self.view_mode == "details" else min(lim, 3000)

    def _search_args(self, limit=None):
        return dict(text=self.entry.get(), category=self.category, case=self.opt_case.get(),
                    regex=self.opt_regex.get(), in_path=self.opt_path.get(), scope=list(self.scope),
                    sort_key=self.sort_key, sort_rev=self.sort_rev, limit=limit or self._limit(), cats=self.cats)

    def _empty_text(self):
        if self.index.scanning and not len(self.index):
            return "Indexing your files…"
        if not len(self.index):
            return "Nothing indexed yet"
        return "No results"

    def _run_search(self):
        self.seq += 1
        seq, args = self.seq, self._search_args()
        self.highlight = highlight_terms(args["text"])
        def work():
            rows, total, err = self.index.search(cancel=lambda: seq != self.seq, **args)
            if seq == self.seq:
                self.ui(lambda: self._got(seq, rows, total, err))
        threading.Thread(target=work, daemon=True).start()

    def _got(self, seq, rows, total, err):
        if seq != self.seq:
            return
        self.error = err
        self._show_rows(rows, total)

    def _show_rows(self, rows, total):
        keep = {it[2] for it in self.selected()}
        self.results, self.total = rows, total
        self.view.empty_text = self._empty_text()
        self.view.set_items(rows, keep)
        self._tab_title()
        self._status()
        self._update_preview()

    # =====================================================================  status
    def _status(self):
        sel = self.selected()
        parts = []
        if self.error:
            parts.append(f"⚠ {self.error}")
        extra = f" (showing first {len(self.results):,})" if self.total > len(self.results) else ""
        parts.append(f"{self.total:,} results{extra}")
        if sel:
            sz = sum(i[4] for i in sel if not i[3] and i[4] > 0)
            parts.append(f"{len(sel):,} selected" + (f" · {human_size(sz)}" if sz else ""))
        ix = self.index
        if ix.scanning:
            parts.append("Indexing…")
        else:
            parts.append(f"{len(ix):,} items indexed")
        if ix.filling and ix.fill_progress[1]:
            parts.append(f"reading details {ix.fill_progress[0] * 100 // ix.fill_progress[1]}%")
        if ix.mode == "ntfs":
            parts.append("⚡ NTFS instant")
        if self.watcher.observer:
            parts.append("● Live")
        self.status.configure(text="   •   ".join(parts))

    # =====================================================================  views
    def set_view(self, mode, rebuild_only=False):
        keep = {it[2] for it in self.selected()} if self.view else set()
        if self.view:
            self.view.destroy()
        self.view_mode = mode
        if not rebuild_only:
            self.settings["view"] = mode
            self.settings.save()
        if mode == "details":
            self.view = VirtualDetails(self.card, self)
        else:
            self.view = ThumbView(self.card, self, THUMB[mode])
        self.view.grid(row=0, column=0, sticky="nsew", padx=4, pady=4)
        self.view.set_sort(self.sort_key, self.sort_rev)
        self.view.empty_text = self._empty_text()
        if not rebuild_only:
            self._run_search() if mode == "details" or len(self.results) > 3000 else self.view.set_items(self.results, keep)
            self._update_preview()

    def view_menu(self):
        m = self._menu()
        var = tk.StringVar(value=self.view_mode)
        for k, label in VIEWS:
            m.add_radiobutton(label=label, value=k, variable=var, command=lambda k=k: self.set_view(k))
        self._popup(m, self.view_btn)

    def toggle_preview(self):
        self.set_preview(not self.preview_on)

    def set_preview(self, on):
        self.preview_on = on
        self.settings["preview"] = on
        self.settings.save()
        if on:
            self.pf.grid(row=0, column=1, sticky="ns", padx=(10, 0))
            self._update_preview()
        else:
            self.pf.grid_remove()

    def toggle_sidebar(self):
        self.set_sidebar(not self.settings["sidebar"])

    def set_sidebar(self, on):
        self.settings["sidebar"] = on
        self.settings.save()
        if on:
            self.side_panel.grid()
        else:
            self.side_panel.grid_remove()

    def toggle_theme(self):
        self.apply_theme("light" if theme.is_dark() else "dark")

    def apply_theme(self, mode):
        ctk.set_appearance_mode(mode)
        self.settings["theme"] = mode
        self.settings.save()
        self.view.restyle()
        self.apply_glass()
        self.refresh_sidebar()
        for w in (self.dup_win, self.settings_win):
            if w is not None and w.winfo_exists():
                theme.win11_titlebar(w)

    # =====================================================================  menus
    def _menu(self):
        m = tk.Menu(self, tearoff=0)
        theme.style_menu(m)
        return m

    def _popup(self, m, widget):
        try:
            m.tk_popup(widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 4)
        finally:
            m.grab_release()

    def tools_menu(self):
        m = self._menu()
        m.add_command(label="New tab                      Ctrl+T", command=self.new_tab)
        m.add_command(label="New window                Ctrl+N", command=lambda: shell.new_window())
        m.add_separator()
        m.add_command(label="Find duplicate files…     Ctrl+Shift+D", command=self.open_duplicates)
        m.add_command(label="Search inside files…", command=self.search_in_files)
        m.add_command(label="Search only in a folder…", command=self.choose_scope)
        m.add_separator()
        m.add_command(label="Add folder or drive to index…", command=self.add_location_dialog)
        m.add_command(label="Rebuild index                F5", command=self.reindex)
        m.add_separator()
        m.add_command(label="Export results…", command=self.export_results)
        m.add_command(label="Export backup (settings, bookmarks)…", command=self.export_backup)
        m.add_command(label="Import backup or list of paths…", command=self.import_backup)
        m.add_separator()
        m.add_command(label="Settings                    Ctrl+,", command=self.open_settings)
        self._popup(m, self.tools_btn)

    def options_menu(self):
        m = self._menu()
        m.add_checkbutton(label="Match case", variable=self.opt_case, command=self._run_search)
        m.add_checkbutton(label="Regular expression", variable=self.opt_regex, command=self._run_search)
        m.add_checkbutton(label="Search in full path", variable=self.opt_path, command=self._run_search)
        m.add_separator()
        m.add_checkbutton(label="Live updates", variable=self.opt_live, command=self._live_toggled)
        m.add_separator()
        m.add_command(label="Search help…", command=self.search_help)
        self._popup(m, self.opt_btn)

    def search_help(self):
        messagebox.showinfo("Search tips",
                            "report 2026        all words must match\n"
                            "\"annual report\"    exact phrase\n"
                            "jpg|png            either word\n"
                            "!draft             leave out 'draft'\n"
                            "*.pdf   img_??     wildcards\n"
                            "ext:pdf;docx       by extension\n"
                            "size:>10mb  size:1mb..5mb  size:empty\n"
                            "dm:today  dm:week  dm:2026-11  dm:>2026-01-01   (date modified)\n"
                            "dc:thisweek        date created / added\n"
                            "folder:  file:     only folders / only files\n"
                            "path:projects      inside folders with this name\n"
                            "type:pictures      a file type (also your own types)\n"
                            "regex:^IMG_\\d+     regular expression on the name",
                            parent=self)

    def show_context(self, x, y):
        sel = self.selected()
        if not sel:
            return
        m = self._menu()
        one = sel[0]
        m.add_command(label="Open", command=self.open_selected)
        m.add_command(label="Open containing folder", command=self.open_folder)
        if one[3]:
            m.add_command(label="Search inside this folder", command=lambda: self.set_scope([one[2]]))
            m.add_command(label="Search inside it in a new tab", command=lambda: self.new_tab(scope=[one[2]]))
        if IS_WIN:
            m.add_command(label="Open terminal here", command=lambda: shell.open_terminal(one[2] if one[3] else os.path.dirname(one[2])))
        m.add_separator()
        m.add_command(label="Copy full path          Ctrl+C", command=self.copy_path)
        m.add_command(label="Copy name", command=self.copy_name)
        if IS_WIN:
            m.add_command(label="Copy file (to paste in Explorer)", command=self.copy_file)
        m.add_separator()
        marked = any(b["path"] == one[2] for b in self.settings["bookmarks"])
        m.add_command(label=("Remove bookmark" if marked else "Add to bookmarks") + "   Ctrl+D", command=self.bookmark_selected)
        m.add_command(label="Rename                    F2", command=self.rename_selected)
        m.add_command(label="Delete (Recycle Bin)   Del", command=self.delete_selected)
        if IS_WIN:
            m.add_command(label="Properties               Alt+Enter", command=self.properties_selected)
        try:
            m.tk_popup(x, y)
        finally:
            m.grab_release()

    # =====================================================================  selection / actions
    def selected(self):
        return self.view.selected() if self.view else []

    def selection_changed(self):
        if self.sel_id:
            self.after_cancel(self.sel_id)
        self.sel_id = self.after(70, lambda: (self._update_preview(), self._status()))

    def open_selected(self):
        sel = self.selected()
        folder_mode = self.settings["double_click"] == "folder"
        for it in sel[:5]:
            try:
                shell.show_in_explorer(it[2]) if folder_mode else shell.open_path(it[2])
            except Exception as ex:
                self.status.configure(text=f"Could not open: {ex}")

    def open_folder(self):
        for it in self.selected()[:5]:
            shell.show_in_explorer(it[2])

    def _clip(self, text):
        self.clipboard_clear()
        self.clipboard_append(text)

    def copy_path(self):
        s = self.selected()
        if s:
            self._clip("\n".join(i[2] for i in s))

    def copy_name(self):
        s = self.selected()
        if s:
            self._clip("\n".join(i[0] for i in s))

    def copy_file(self):
        s = self.selected()
        if s:
            shell.copy_files_to_clipboard([i[2] for i in s])

    def properties_selected(self):
        s = self.selected()
        if s:
            shell.show_properties(s[0][2])

    def bookmark_selected(self):
        s = self.selected()
        if not s:
            return
        bm = self.settings["bookmarks"]
        for it in s:
            if any(b["path"] == it[2] for b in bm):
                bm = [b for b in bm if b["path"] != it[2]]
            else:
                bm = bm + [{"path": it[2], "name": it[0]}]
        self.settings["bookmarks"] = bm
        self.settings.save()
        self.refresh_sidebar()

    def rename_selected(self):
        s = self.selected()
        if not s:
            return
        it = s[0]
        new = simpledialog.askstring("Rename", "New name:", initialvalue=it[0], parent=self)
        if not new or new == it[0]:
            return
        dst = os.path.join(os.path.dirname(it[2]), new)
        try:
            os.rename(it[2], dst)
        except OSError as e:
            messagebox.showerror("Rename", f"Could not rename:\n{e}", parent=self)
            return
        self.index.remove(it[2])
        self.index.add(dst, deep=it[3])
        self._run_search()

    def delete_selected(self):
        s = self.selected()
        if not s:
            return
        msg = f"Move “{s[0][0]}” to the Recycle Bin?" if len(s) == 1 else f"Move {len(s):,} items to the Recycle Bin?"
        if not messagebox.askyesno("Delete", msg, parent=self):
            return
        res = shell.trash([i[2] for i in s])
        for p, err in res:
            if err is None:
                self.index.remove(p)
        bad = [e for _, e in res if e]
        if bad:
            messagebox.showerror("Delete", f"{len(bad)} item(s) could not be deleted.\n{bad[0]}", parent=self)
        self._run_search()

    # =====================================================================  preview pane
    def _set_text(self, s):
        self.p_text.configure(state="normal")
        self.p_text.delete("1.0", "end")
        self.p_text.insert("1.0", s)
        self.p_text.configure(state="disabled")

    def _update_preview(self):
        if not self.preview_on:
            return
        sel = self.selected()
        self.p_thumb.grid_remove()
        self.p_text.grid_remove()
        self.p_icon.grid()
        if not sel:
            self.p_icon.configure(text="🔍")
            self.p_name.configure(text="Select a file to preview")
            self.p_meta.configure(text="")
            return
        name, _ln, path, is_dir, size, mt, ext, ct = sel[0]
        meta = f"Type:  {type_name(ext, is_dir)}\n" + ("" if is_dir or size < 0 else f"Size:  {human_size(size)}\n")
        if mt > 86400:
            meta += f"Modified:  {human_date(mt)}\n"
        if ct > 86400:
            meta += f"Created:  {human_date(ct)}\n"
        meta += f"Location:  {os.path.dirname(path)}"
        if len(sel) > 1:
            meta += f"\n\n+ {len(sel) - 1} more selected"
        self.p_name.configure(text=name)
        self.p_meta.configure(text=meta)
        self.p_icon.configure(text="📁" if is_dir else "📄")
        try:
            if is_dir:
                names = sorted(os.listdir(path), key=str.lower)
                self._set_text(f"{len(names)} items\n\n" + "\n".join(names[:25]) + ("\n…" if len(names) > 25 else ""))
                self.p_text.grid()
            elif ext in THUMB_EXT and (size < 0 or size < 400 * 1024 * 1024):
                self._preview_async(path)
            elif ext in TEXT_EXT:
                with open(path, "rb") as f:
                    data = f.read(4000)
                self._set_text(data.decode("utf-8", errors="replace"))
                self.p_text.grid()
        except Exception:
            pass

    def _preview_async(self, path):
        """pictures, PDFs, videos, Office files: make the thumbnail in the background"""
        def work():
            im = get_thumbnail(path, 520)
            self.ui(lambda: self._preview_ready(path, im))
        threading.Thread(target=work, daemon=True).start()

    def _preview_ready(self, path, im):
        sel = self.selected()
        if im is None or not sel or sel[0][2] != path or not self.preview_on:
            return
        im.thumbnail((262, 260))
        self._thumb = ctk.CTkImage(light_image=im, dark_image=im, size=im.size)
        self.p_thumb.configure(image=self._thumb)
        self.p_icon.grid_remove()
        self.p_thumb.grid()

    # =====================================================================  sidebar
    def refresh_sidebar(self):
        sb = self.sidebar
        sb.restyle()
        sb.clear()
        sb.header("Quick filters")
        for label, q in QUICK:
            sb.row(label, lambda q=q: self._set_query(q))
        sb.header("Drives", ("＋ Add", self.add_location_dialog))
        from engine import list_drives
        for d in list_drives():
            icon = "🔌" if d["kind"] == "removable" else "💽"
            sb.row(f"{icon}  {d['root']}  {d['label']}".strip(), lambda r=d["root"]: self.set_scope([r]))
        for p in self.settings["extra_locations"]:
            sb.row(f"📂  {clip(p, 26)}", lambda p=p: self.set_scope([p]))
        bms = self.settings["bookmarks"]
        sb.header("Bookmarks")
        if not bms:
            sb.note("Select a result and press Ctrl+D")
        for b in bms:
            sb.row("🔖  " + clip(b["name"], 26), lambda b=b: self._open_bookmark(b), lambda e, b=b: self._bookmark_menu(e, b))
        sb.header("Saved searches", ("＋ Save", self.save_search))
        for s_ in self.settings["saved"]:
            sb.row("★  " + clip(s_["name"], 26), lambda s_=s_: self.apply_saved(s_), lambda e, s_=s_: self._saved_menu(e, s_))
        sb.header("History", ("Clear", self.clear_history))
        for h in self.settings["history"][:12]:
            sb.row("🕘  " + clip(h["q"], 26), lambda q=h["q"]: self._set_query(q))

    def _set_query(self, q):
        self.entry.delete(0, "end")
        if q:
            self.entry.insert(0, q)
        self._run_search()

    def _open_bookmark(self, b):
        if os.path.exists(b["path"]):
            shell.open_path(b["path"])
        else:
            self.status.configure(text=f"Bookmark not found: {b['path']}")

    def _bookmark_menu(self, e, b):
        m = self._menu()
        m.add_command(label="Open", command=lambda: self._open_bookmark(b))
        m.add_command(label="Open containing folder", command=lambda: shell.show_in_explorer(b["path"]))
        if os.path.isdir(b["path"]):
            m.add_command(label="Search inside this folder", command=lambda: self.set_scope([b["path"]]))
        m.add_separator()
        m.add_command(label="Remove bookmark", command=lambda: self._rm_bookmark(b))
        m.tk_popup(e.x_root, e.y_root)

    def _rm_bookmark(self, b):
        self.settings["bookmarks"] = [x for x in self.settings["bookmarks"] if x["path"] != b["path"]]
        self.settings.save()
        self.refresh_sidebar()

    def _saved_menu(self, e, s):
        m = self._menu()
        m.add_command(label="Run", command=lambda: self.apply_saved(s))
        m.add_command(label="Delete", command=lambda: self._rm_saved(s))
        m.tk_popup(e.x_root, e.y_root)

    def _rm_saved(self, s):
        self.settings["saved"] = [x for x in self.settings["saved"] if x["name"] != s["name"]]
        self.settings.save()
        self.refresh_sidebar()

    def save_search(self):
        q = self.entry.get().strip()
        if not q and self.category == "All" and not self.scope:
            self.status.configure(text="Type a search (or pick a filter) first, then save it.")
            return
        name = ctk.CTkInputDialog(text="Name for this search:", title="Save search").get_input()
        if not name:
            return
        saved = [s for s in self.settings["saved"] if s["name"] != name]
        saved.append({"name": name, "query": q, "category": self.category, "case": self.opt_case.get(),
                      "regex": self.opt_regex.get(), "path": self.opt_path.get(), "scope": list(self.scope),
                      "sort_key": self.sort_key, "sort_rev": self.sort_rev})
        self.settings["saved"] = saved
        self.settings.save()
        self.refresh_sidebar()

    def apply_saved(self, s):
        self.entry.delete(0, "end")
        if s["query"]:
            self.entry.insert(0, s["query"])
        self.category = s.get("category", "All") if s.get("category") in self.cats else "All"
        self.seg.set(self.category)
        self.opt_case.set(s.get("case", False)); self.opt_regex.set(s.get("regex", False)); self.opt_path.set(s.get("path", False))
        self.scope = list(s.get("scope", []))
        self.sort_key, self.sort_rev = s.get("sort_key", self.sort_key), s.get("sort_rev", self.sort_rev)
        self._sync_sort_ui()
        self._update_scope_chip()
        self._run_search()

    def clear_history(self):
        self.settings["history"] = []
        self.settings.save()
        self.refresh_sidebar()

    # =====================================================================  tools
    def open_duplicates(self):
        from dupes import DupWindow
        self.show_window()
        if self.dup_win is not None and self.dup_win.winfo_exists():
            self.dup_win.lift()
            return
        self.dup_win = DupWindow(self)

    def open_settings(self):
        from settings_ui import SettingsWindow
        if self.settings_win is not None and self.settings_win.winfo_exists():
            self.settings_win.lift()
            return
        self.settings_win = SettingsWindow(self)

    def search_in_files(self):
        text = ctk.CTkInputDialog(text="Find files that contain this text\n(searches the results shown now: text files and Word docs):",
                                  title="Search inside files").get_input()
        if not text:
            return
        rows = [r for r in self.results if not r[3] and (r[6] in TEXT_EXT or r[6] == ".docx")][:5000]
        if not rows:
            self.status.configure(text="No text files in the current results. Narrow the search first (for example ext:txt).")
            return
        needle = text.lower()
        def work():
            hits = []
            for n, it in enumerate(rows):
                try:
                    if os.path.getsize(it[2]) > 8 << 20:
                        continue
                    if it[6] == ".docx":
                        with zipfile.ZipFile(it[2]) as z:
                            data = re.sub(r"<[^>]+>", " ", z.read("word/document.xml").decode("utf-8", "ignore"))
                    else:
                        with open(it[2], "rb") as f:
                            data = f.read().decode("utf-8", "ignore")
                    if needle in data.lower():
                        hits.append(it)
                except Exception:
                    pass
                if n % 25 == 0:
                    self.ui(lambda n=n: self.status.configure(text=f"Searching inside files… {n:,} / {len(rows):,}   ({len(hits)} found)"))
            self.ui(lambda: self._content_done(text, hits))
        threading.Thread(target=work, daemon=True).start()

    def _content_done(self, text, hits):
        self.seq += 1
        self.tabs[self.cur]["title"] = f"Contains: {text}"
        self._rebuild_tabs()
        self.results, self.total = hits, len(hits)
        self.view.set_items(hits)
        self._status()
        self.status.configure(text=f"{len(hits):,} files contain “{text}”   •   (new search to go back)")

    def export_results(self):
        f = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="findit-results.csv",
                                         filetypes=[("CSV (Excel)", "*.csv"), ("JSON", "*.json"), ("List of paths", "*.txt")])
        if not f:
            return
        args = self._search_args(limit=10 ** 9)
        def work():
            rows, total, _ = self.index.search(**args)
            ext = os.path.splitext(f)[1].lower()
            try:
                if ext == ".json":
                    data = [{"name": r[0], "path": r[2], "folder": r[3], "size": r[4], "modified": human_date(r[5]),
                             "created": human_date(r[7])} for r in rows]
                    with open(f, "w", encoding="utf-8") as fh:
                        json.dump(data, fh, indent=1, ensure_ascii=False)
                elif ext == ".txt":
                    with open(f, "w", encoding="utf-8") as fh:
                        fh.write("\n".join(r[2] for r in rows))
                else:
                    with open(f, "w", newline="", encoding="utf-8-sig") as fh:
                        w = csv.writer(fh)
                        w.writerow(["Name", "Location", "Size (bytes)", "Type", "Modified", "Created"])
                        for r in rows:
                            w.writerow([r[0], os.path.dirname(r[2]), r[4] if not r[3] else "", type_name(r[6], r[3]),
                                        human_date(r[5]), human_date(r[7])])
                msg = f"Exported {len(rows):,} results to {f}"
            except OSError as e:
                msg = f"Export failed: {e}"
            self.ui(lambda: self.status.configure(text=msg))
        threading.Thread(target=work, daemon=True).start()

    def export_backup(self):
        f = filedialog.asksaveasfilename(parent=self, defaultextension=".json", initialfile="findit-backup.json",
                                         filetypes=[("FindIt backup", "*.json")])
        if not f:
            return
        keep = {k: v for k, v in self.settings.data.items() if k not in ("admin", "admin_asked")}
        with open(f, "w", encoding="utf-8") as fh:
            json.dump({"findit_backup": 2, "settings": keep}, fh, indent=2)
        self.status.configure(text=f"Backup saved: {f}")

    def import_backup(self):
        f = filedialog.askopenfilename(parent=self, filetypes=[("Backup or list", "*.json *.txt *.csv"), ("All files", "*.*")])
        if not f:
            return
        s = self.settings
        try:
            with open(f, "r", encoding="utf-8-sig") as fh:
                raw = fh.read()
            if f.lower().endswith(".json") and '"findit_backup"' in raw:
                data = json.loads(raw)["settings"]
                for k, v in data.items():
                    if k in ("bookmarks", "saved", "history"):
                        key = {"bookmarks": "path", "saved": "name", "history": "q"}[k]
                        have = {x[key] for x in s[k]}
                        s[k] = s[k] + [x for x in v if x.get(key) not in have]
                    elif k in s.data and k not in ("admin", "admin_asked"):
                        s[k] = v
                s.save()
                msg = "Backup imported."
            else:
                added = 0
                have = {b["path"] for b in s["bookmarks"]}
                for line in raw.splitlines():
                    p = line.strip().strip('"').split(",")[0].strip('"')
                    if p and os.path.exists(p) and p not in have:
                        s["bookmarks"] = s["bookmarks"] + [{"path": p, "name": os.path.basename(p) or p}]
                        added += 1
                s.save()
                msg = f"Added {added} bookmarks from the list."
        except Exception as e:
            msg = f"Import failed: {e}"
        self.refresh_categories()
        self.refresh_sidebar()
        self.status.configure(text=msg)

    # =====================================================================  indexing
    def _startup(self):
        self.status.configure(text="Loading…")
        self.index.new_drives()          # remember which drives exist now
        def work():
            loaded = self.index.load_cache()
            self.ui(lambda: (self._run_search(), self._decide_rescan(loaded)))
        threading.Thread(target=work, daemon=True).start()
        if self.opt_live.get():
            self._live_toggled()

    def _decide_rescan(self, loaded):
        pol = self.settings["rescan"]
        age = (time.time() - self.index.cache_time) / 3600 if self.index.cache_time else 1e9
        instant = IS_WIN and is_admin()
        stale = age > float(self.settings["rescan_hours"])
        if (not loaded) or pol == "always" or (pol == "auto" and (instant or stale)) or (pol == "stale" and stale):
            self.reindex()
        else:
            self.status.configure(text=f"Using the saved index ({age:.1f} h old)…")
            threading.Thread(target=self.index.fill_details, daemon=True).start()

    def reindex(self):
        if self.index.scanning:
            return
        def prog(n):
            self.ui(lambda: self.status.configure(text=f"Indexing…  {n:,} items"))
        def work():
            t = time.time()
            self.index.build(progress=prog)
            dt = time.time() - t
            self.ui(lambda: self._index_done(dt))
            self.index.fill_details()
        threading.Thread(target=work, daemon=True).start()

    def _index_done(self, dt):
        self._run_search()
        if self.state() != "normal":
            self.notify("FindIt is ready", f"{len(self.index):,} items indexed in {dt:.1f}s")

    def index_location(self, path):
        def work():
            n = self.index.index_extra(path)
            self.ui(lambda: (self._run_search(), self.refresh_sidebar(),
                                   self.notify("Location indexed", f"{path}: {n:,} items")))
            self.index.fill_details()
        threading.Thread(target=work, daemon=True).start()

    def add_location_dialog(self):
        d = filedialog.askdirectory(parent=self, title="Choose a folder or drive to index")
        if d:
            d = os.path.normpath(d)
            if d not in self.settings["extra_locations"]:
                self.settings["extra_locations"] = self.settings["extra_locations"] + [d]
                self.settings.save()
                self.index_location(d)

    def _live_toggled(self):
        self.settings["live"] = self.opt_live.get()
        self.settings.save()
        if self.opt_live.get():
            if not Watcher.available():
                self.opt_live.set(False)
                self.status.configure(text="Live updates need the 'watchdog' package:  pip install watchdog")
                return
            threading.Thread(target=self.watcher.start, daemon=True).start()
        else:
            threading.Thread(target=self.watcher.stop, daemon=True).start()

    def _poll(self):
        self._poll_n += 1
        busy = self.index.scanning or self.index.filling
        every = 4 if busy else 2
        if self.index.dirty and not self.index.scanning and self._poll_n % every == 0 and self.state() == "normal":
            self.index.dirty = False
            self._run_search()
        if self._poll_n % 5 == 0:
            for d in self.index.new_drives():
                if d["kind"] in ("fixed", "removable") and self.settings["auto_new_drives"] and \
                        d["letter"].upper() not in {x.upper() for x in self.settings["skip_drives"]}:
                    self.index_location(d["root"])
                    self.refresh_sidebar()
        if self.state() == "normal":
            self._status()
        self.after(1000, self._poll)

    # =====================================================================  tray / window
    def notify(self, title, msg):
        if self.settings["notify"]:
            self.tray.notify(title, msg)

    def apply_tray(self):
        if IS_WIN and self.settings["tray"]:
            self.tray.start()
        else:
            self.tray.stop()

    def apply_hotkey(self):
        if IS_WIN and self.settings["hotkey"]:
            self.hotkey.start()
        else:
            self.hotkey.stop()

    def show_window(self):
        self.deiconify()
        self.lift()
        self.focus_force()
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def _on_close(self):
        if self.settings["close_to_tray"] and self.tray.icon:
            self.withdraw()
            self.notify("FindIt is still running", "Click the tray icon to open it again, or press Ctrl+Alt+Space.")
        else:
            self._quit()

    def _quit(self):
        try:
            self.index.stop = True
            self.watcher.stop()
            self.tray.stop()
            self.hotkey.stop()
            self.ipc.stop()
            self._save_tab()
            try:
                if self.state() == "normal":
                    self.settings["geometry"] = self.geometry()
            except Exception:
                pass
            self.settings.save()
            if self.index.dirty and len(self.index) and not self.index.scanning:
                self.index.save_cache()
        finally:
            self.destroy()

    def _first_run(self):
        if IS_WIN and not self.settings["admin_asked"] and not is_admin():
            self.settings["admin_asked"] = True
            self.settings.save()
            if messagebox.askyesno(
                    "Make FindIt instant?",
                    "FindIt can index your whole PC in a few seconds (like Everything) by reading the NTFS file table, "
                    "but Windows only allows that with administrator permission.\n\n"
                    "Turn it on? Windows will ask for permission when FindIt starts.", parent=self):
                self.settings["admin"] = True
                self.settings.save()
                if shell.relaunch_as_admin(["--elevated"]):
                    self._quit()


def run(args):
    settings = Settings()
    if IS_WIN and settings["admin"] and not is_admin() and not args.elevated:
        if shell.relaunch_as_admin(sys.argv[1:] + ["--elevated"]):
            return
    App(args, settings).mainloop()
