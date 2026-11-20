"""Duplicate finder: keeps the newest copy, lets you delete the older ones (to the Recycle Bin)."""
import os, hashlib, threading
from tkinter import ttk, messagebox, filedialog
from collections import defaultdict
import customtkinter as ctk
import theme
from theme import THEME, FONT
from engine import human_size, human_date
import shell


def _hash(path, limit=None):
    h = hashlib.blake2b(digest_size=16)
    try:
        with open(path, "rb") as f:
            left = limit
            while True:
                n = 1 << 20 if left is None else min(1 << 20, left)
                if n <= 0:
                    break
                b = f.read(n)
                if not b:
                    break
                h.update(b)
                if left is not None:
                    left -= len(b)
    except OSError:
        return None
    return h.digest()


def find_duplicates(index, items, mode="content", min_size=1, cancel=lambda: False, progress=None):
    """-> list of {'size': int, 'items': [item,...]} (each group newest first, biggest waste first)"""
    files = index.ensure_details([it for it in items if not it[3]])
    by = defaultdict(list)
    for it in files:
        if it[4] >= min_size and it[4] >= 0:
            by[it[4] if mode == "content" else (it[1], it[4])].append(it)
    cands = [g for g in by.values() if len(g) > 1]
    groups = []
    if mode != "content":
        groups = cands
    else:
        total = sum(len(g) for g in cands) or 1
        done = 0
        for g in cands:
            if cancel():
                break
            part = defaultdict(list)
            for it in g:
                h = _hash(it[2], 65536)
                if h:
                    part[h].append(it)
                done += 1
            for sg in part.values():
                if len(sg) < 2:
                    continue
                if sg[0][4] <= 65536:
                    groups.append(sg)
                    continue
                full = defaultdict(list)
                for it in sg:
                    if cancel():
                        break
                    h = _hash(it[2])
                    if h:
                        full[h].append(it)
                groups.extend(x for x in full.values() if len(x) > 1)
            if progress:
                progress(done, total)
    out = []
    for g in groups:
        g = sorted(g, key=lambda i: i[5], reverse=True)   # newest first
        out.append({"size": g[0][4], "items": g})
    out.sort(key=lambda d: d["size"] * (len(d["items"]) - 1), reverse=True)
    return out


class DupWindow(ctk.CTkToplevel):
    def __init__(self, app):
        super().__init__(app, fg_color=THEME["bg"])
        self.app = app
        self.title("Find duplicate files")
        self.geometry("1000x680")
        self.minsize(760, 480)
        self.transient(app)
        self.groups, self.marked = [], set()
        self.cancel = False
        self.running = False
        self.after(150, lambda: theme.win11_titlebar(self))
        self.protocol("WM_DELETE_WINDOW", self._close)
        self._build()

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(2, weight=1)
        ctk.CTkLabel(self, text="Find duplicate files", font=(FONT, 20, "bold"),
                     text_color=THEME["text"]).grid(row=0, column=0, sticky="w", padx=20, pady=(16, 2))
        opt = ctk.CTkFrame(self, fg_color="transparent")
        opt.grid(row=1, column=0, sticky="ew", padx=20, pady=(4, 8))
        self.scope = ctk.CTkSegmentedButton(opt, values=["Current results", "Whole index"], font=(FONT, 12),
                                            selected_color=THEME["accent"], unselected_color=THEME["hover"],
                                            text_color=THEME["text"], fg_color=THEME["hover"])
        self.scope.set("Current results")
        self.scope.pack(side="left")
        self.mode = ctk.CTkOptionMenu(opt, values=["Same content (accurate)", "Same name and size (fast)"],
                                      width=210, font=(FONT, 12), fg_color=THEME["hover"],
                                      button_color=THEME["stroke"], text_color=THEME["text"])
        self.mode.pack(side="left", padx=10)
        self.minsize_menu = ctk.CTkOptionMenu(opt, values=["Any size", "Over 100 KB", "Over 1 MB", "Over 10 MB", "Over 100 MB"],
                                              width=130, font=(FONT, 12), fg_color=THEME["hover"],
                                              button_color=THEME["stroke"], text_color=THEME["text"])
        self.minsize_menu.pack(side="left")
        self.go = ctk.CTkButton(opt, text="Scan", width=90, fg_color=THEME["accent"], font=(FONT, 13, "bold"),
                                command=self.start)
        self.go.pack(side="left", padx=10)
        self.info = ctk.CTkLabel(opt, text="", font=(FONT, 12), text_color=THEME["sub"])
        self.info.pack(side="left", padx=6)

        card = ctk.CTkFrame(self, fg_color=THEME["card"], corner_radius=10, border_width=1, border_color=THEME["stroke"])
        card.grid(row=2, column=0, sticky="nsew", padx=20)
        card.grid_columnconfigure(0, weight=1)
        card.grid_rowconfigure(0, weight=1)
        theme.style_tree("Dup.Treeview", 30)
        self.tree = ttk.Treeview(card, columns=("action", "age", "size", "date", "path"), show="tree headings",
                                 selectmode="browse", style="Dup.Treeview")
        for c, t, w, a in (("#0", "File", 280, "w"), ("action", "Action", 80, "w"), ("age", "Age", 80, "w"),
                           ("size", "Size", 80, "e"), ("date", "Modified", 140, "w"), ("path", "Location", 380, "w")):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, minwidth=50)
        self.tree.tag_configure("group", font=(FONT, 11, "bold"))
        self.tree.tag_configure("del", foreground="#D13438")
        self.tree.tag_configure("keep", foreground="#107C10")
        sb = ctk.CTkScrollbar(card, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 4))
        self.tree.bind("<Button-1>", self._click)
        self.tree.bind("<Double-1>", self._dbl)

        bar = ctk.CTkFrame(self, fg_color="transparent")
        bar.grid(row=3, column=0, sticky="ew", padx=20, pady=(8, 14))
        def btn(text, cmd, **kw):
            b = ctk.CTkButton(bar, text=text, command=cmd, font=(FONT, 12), height=34,
                              fg_color=kw.pop("fg", THEME["hover"]), hover_color=THEME["stroke"],
                              text_color=kw.pop("tc", THEME["text"]), border_width=1, border_color=THEME["stroke"], **kw)
            b.pack(side="left", padx=(0, 8))
            return b
        btn("Keep newest, mark older", lambda: self.auto("newest"))
        btn("Keep oldest, mark newer", lambda: self.auto("oldest"))
        btn("Clear marks", lambda: self.auto("none"))
        btn("Export report…", self.export)
        self.summary = ctk.CTkLabel(bar, text="", font=(FONT, 12), text_color=THEME["sub"])
        self.summary.pack(side="left", padx=8)
        self.del_btn = ctk.CTkButton(bar, text="Delete marked (Recycle Bin)", command=self.delete, height=34,
                                     fg_color=THEME["danger"], hover_color="#A52318", font=(FONT, 12, "bold"),
                                     state="disabled")
        self.del_btn.pack(side="right")

    # ---- scanning
    def start(self):
        if self.running:
            self.cancel = True
            return
        items = list(self.app.results) if self.scope.get() == "Current results" else list(self.app.index.map.values())
        if self.scope.get() == "Current results" and not self.app.results:
            self.info.configure(text="No results to check - search first, or use 'Whole index'.")
            return
        mode = "content" if self.mode.get().startswith("Same content") else "namesize"
        ms = {"Any size": 1, "Over 100 KB": 100 << 10, "Over 1 MB": 1 << 20, "Over 10 MB": 10 << 20, "Over 100 MB": 100 << 20}[self.minsize_menu.get()]
        self.running, self.cancel = True, False
        self.go.configure(text="Cancel")
        self.info.configure(text="Scanning…")
        def prog(d, t):
            self.app.ui(lambda: self.info.configure(text=f"Comparing files… {d:,} / {t:,}"))
        def work():
            try:
                g = find_duplicates(self.app.index, items, mode, ms, lambda: self.cancel, prog)
            except Exception as e:
                g, msg = [], f"Scan failed: {e}"
                self.app.ui(lambda: self.info.configure(text=msg))
            self.app.ui(lambda: self._done(g))
        threading.Thread(target=work, daemon=True).start()

    def _done(self, groups):
        if not self.winfo_exists():
            return
        self.running = False
        self.go.configure(text="Scan")
        self.groups = groups
        self.marked = set()
        waste = sum(g["size"] * (len(g["items"]) - 1) for g in groups)
        self.info.configure(text=("Cancelled. " if self.cancel else "") +
                            (f"{len(groups):,} duplicate groups · {human_size(waste)} could be freed" if groups
                             else "No duplicates found."))
        self.auto("newest")

    # ---- list
    def _fill(self):
        self.tree.delete(*self.tree.get_children())
        for gi, g in enumerate(self.groups):
            its = g["items"]
            gid = f"g{gi}"
            self.tree.insert("", "end", iid=gid, open=True, tags=("group",),
                             text=f"📎 {its[0][0]}  —  {len(its)} copies",
                             values=("", "", human_size(g["size"]), "", f"{human_size(g['size'] * (len(its) - 1))} wasted"))
            for j, it in enumerate(its):
                m = it[2] in self.marked
                self.tree.insert(gid, "end", iid=f"{gid}_{j}", text="    " + it[0],
                                 values=("🗑 Delete" if m else "✔ Keep", "Newest" if j == 0 else "Older",
                                         human_size(it[4]), human_date(it[5]), os.path.dirname(it[2])),
                                 tags=("del" if m else "keep",))
        self._summary()

    def _summary(self):
        n = len(self.marked)
        size = sum(it[4] for g in self.groups for it in g["items"] if it[2] in self.marked)
        self.summary.configure(text=f"{n:,} marked · {human_size(size)}" if n else "")
        self.del_btn.configure(state="normal" if n else "disabled")

    def auto(self, how):
        self.marked = set()
        for g in self.groups:
            its = g["items"]
            if how == "newest":
                self.marked.update(i[2] for i in its[1:])
            elif how == "oldest":
                self.marked.update(i[2] for i in its[:-1])
        self._fill()

    def _click(self, e):
        row = self.tree.identify_row(e.y)
        if not row or "_" not in row:
            return
        gi, j = (int(x) for x in row[1:].split("_"))
        its = self.groups[gi]["items"]
        p = its[j][2]
        if p in self.marked:
            self.marked.discard(p)
        elif sum(1 for i in its if i[2] not in self.marked) <= 1:
            self.info.configure(text="Keep at least one copy of each file.")
            return
        else:
            self.marked.add(p)
        m = p in self.marked
        self.tree.item(row, tags=("del" if m else "keep",),
                       values=("🗑 Delete" if m else "✔ Keep",) + tuple(self.tree.item(row, "values")[1:]))
        self._summary()

    def _dbl(self, e):
        row = self.tree.identify_row(e.y)
        if row and "_" in row:
            gi, j = (int(x) for x in row[1:].split("_"))
            shell.show_in_explorer(self.groups[gi]["items"][j][2])

    # ---- actions
    def delete(self):
        paths = list(self.marked)
        if not paths:
            return
        size = sum(it[4] for g in self.groups for it in g["items"] if it[2] in self.marked)
        if not messagebox.askyesno("Delete older copies",
                                   f"Move {len(paths):,} files ({human_size(size)}) to the Recycle Bin?\n\n"
                                   "You can restore them from the Recycle Bin if needed.", parent=self):
            return
        res = shell.trash(paths)
        ok = [p for p, err in res if err is None]
        bad = [(p, err) for p, err in res if err]
        for p in ok:
            self.app.index.remove(p)
        done = set(ok)
        for g in self.groups:
            g["items"] = [i for i in g["items"] if i[2] not in done]
        self.groups = [g for g in self.groups if len(g["items"]) > 1]
        self.marked -= done
        self._fill()
        msg = f"Moved {len(ok):,} files to the Recycle Bin ({human_size(size)} freed)."
        if bad:
            msg += f"  {len(bad)} could not be deleted."
        self.info.configure(text=msg)
        self.app.notify("Duplicates removed", msg)
        self.app._run_search()

    def export(self):
        if not self.groups:
            return
        f = filedialog.asksaveasfilename(parent=self, defaultextension=".csv", initialfile="duplicates.csv",
                                         filetypes=[("CSV", "*.csv")])
        if not f:
            return
        import csv
        with open(f, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.writer(fh)
            w.writerow(["group", "action", "name", "size_bytes", "modified", "path"])
            for gi, g in enumerate(self.groups, 1):
                for it in g["items"]:
                    w.writerow([gi, "delete" if it[2] in self.marked else "keep", it[0], it[4], human_date(it[5]), it[2]])
        self.info.configure(text=f"Report saved: {f}")

    def _close(self):
        self.cancel = True
        self.destroy()
