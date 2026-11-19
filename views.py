"""Result views: Details list and Thumbnail grid (small / medium / large / extra large)."""
import os, queue
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk
from PIL import ImageTk
import theme
from theme import THEME, FONT
from engine import human_size, human_date, type_name, kind_of
from thumbs import THUMB_EXT, get_thumbnail

EMOJI = {"Folders": "📁", "Documents": "📄", "Pictures": "🖼", "Audio": "🎵", "Video": "🎬",
         "Apps": "🧩", "Archives": "🗜", "Other": "📄"}
CAT_COLOR = {"Documents": "#2B7BD6", "Pictures": "#2E9E5B", "Audio": "#8E5BD9", "Video": "#D9534F",
             "Apps": "#5C6670", "Archives": "#E08A1E", "Other": "#7A8794"}


def emoji_for(it, cats):
    return EMOJI.get(kind_of(it[6], it[3], cats), "📄")


class DetailsView(ctk.CTkFrame):
    COLS = (("#0", "name", "Name", 260, "w"), ("path", "path", "Location", 260, "w"),
            ("size", "size", "Size", 80, "e"), ("type", "type", "Type", 80, "w"),
            ("date", "date", "Modified", 125, "w"), ("created", "created", "Created", 125, "w"))

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.items = []
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        theme.style_tree()
        self.tree = ttk.Treeview(self, columns=("path", "size", "type", "date", "created"),
                                 show="tree headings", selectmode="extended", style="Fluent.Treeview")
        for col, key, title, w, anchor in self.COLS:
            self.tree.heading(col, text=title, command=lambda k=key: app.sort_by(k))
            grow = col in ("#0", "path")
            self.tree.column(col, width=w, anchor=anchor if col != "#0" else "w", minwidth=110 if grow else 60,
                             stretch=grow)
        sb = ctk.CTkScrollbar(self, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.grid(row=0, column=0, sticky="nsew", padx=(6, 0), pady=6)
        sb.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 4))
        t = self.tree
        t.bind("<Double-1>", lambda e: app.open_selected())
        t.bind("<Return>", lambda e: app.open_selected())
        t.bind("<Button-3>", self._ctx)
        t.bind("<Control-c>", lambda e: app.copy_path())
        t.bind("<<TreeviewSelect>>", lambda e: app.selection_changed())
        t.bind("<Delete>", lambda e: app.delete_selected())
        t.bind("<F2>", lambda e: app.rename_selected())
        t.bind("<Alt-Return>", lambda e: app.properties_selected())
        self.restyle()

    def restyle(self):
        theme.style_tree()
        self.tree.tag_configure("odd", background="#303030" if theme.is_dark() else "#FAFAFA")

    def _ctx(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            if row not in self.tree.selection():
                self.tree.selection_set(row)
            self.app.show_context(e.x_root, e.y_root)

    def set_sort(self, key, rev):
        for col, k, title, _w, _a in self.COLS:
            arrow = (" ▼" if rev else " ▲") if k == key else ""
            self.tree.heading(col, text=title + arrow)

    def set_items(self, items, keep=()):
        pos = self.tree.yview()[0]
        self.items = items
        self.tree.delete(*self.tree.get_children())
        cats, sel = self.app.cats, []
        for n, it in enumerate(items):
            name, _ln, path, is_dir, size, mt, ext, ct = it
            self.tree.insert("", "end", iid=str(n), text=f"{emoji_for(it, cats)}  {name}",
                             values=(os.path.dirname(path), "" if is_dir else human_size(size),
                                     type_name(ext, is_dir), human_date(mt), human_date(ct)),
                             tags=("odd",) if n % 2 else ())
            if path in keep:
                sel.append(str(n))
        if sel:
            self.tree.selection_set(sel)
        if keep:
            self.tree.yview_moveto(pos)

    def selected(self):
        return [self.items[int(i)] for i in self.tree.selection() if int(i) < len(self.items)]

    def focus_first(self):
        kids = self.tree.get_children()
        if kids:
            self.tree.focus_set()
            self.tree.selection_set(kids[0])
            self.tree.focus(kids[0])


class ThumbView(ctk.CTkFrame):
    def __init__(self, master, app, size):
        super().__init__(master, fg_color="transparent")
        self.app, self.S = app, size
        self.tw, self.th = size + 30, size + 56
        self.items, self.sel, self.anchor = [], set(), None
        self.cols = 1
        self.cache = OrderedDict()
        self.pending = set()
        self.q = queue.Queue()
        self.pool = ThreadPoolExecutor(3)
        self.alive = True
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)
        self.cv = tk.Canvas(self, highlightthickness=0, bd=0, yscrollincrement=max(8, self.th // 4))
        self.sb = ctk.CTkScrollbar(self, command=self._yview)
        self.cv.configure(yscrollcommand=self._on_scroll)
        self.cv.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=6)
        self.sb.grid(row=0, column=1, sticky="ns", pady=6, padx=(0, 4))
        cv = self.cv
        cv.bind("<Configure>", lambda e: self._layout())
        cv.bind("<Button-1>", self._click)
        cv.bind("<Control-Button-1>", lambda e: self._click(e, ctrl=True))
        cv.bind("<Shift-Button-1>", lambda e: self._click(e, shift=True))
        cv.bind("<Double-1>", lambda e: app.open_selected())
        cv.bind("<Button-3>", self._ctx)
        cv.bind("<MouseWheel>", lambda e: self._wheel(-1 if e.delta > 0 else 1))
        cv.bind("<Button-4>", lambda e: self._wheel(-1))
        cv.bind("<Button-5>", lambda e: self._wheel(1))
        for k, d in (("Left", -1), ("Right", 1), ("Up", "up"), ("Down", "down")):
            cv.bind(f"<{k}>", lambda e, d=d: self._move(d))
        cv.bind("<Return>", lambda e: app.open_selected())
        cv.bind("<Control-a>", lambda e: self._all())
        cv.bind("<Control-c>", lambda e: app.copy_path())
        cv.bind("<Delete>", lambda e: app.delete_selected())
        cv.bind("<F2>", lambda e: app.rename_selected())
        cv.bind("<Alt-Return>", lambda e: app.properties_selected())
        self.restyle()
        self.after(80, self._drain)

    def destroy(self):
        self.alive = False
        self.pool.shutdown(wait=False, cancel_futures=True)
        super().destroy()

    def restyle(self):
        self.cv.configure(bg="#2B2B2B" if theme.is_dark() else "#FFFFFF")
        self.redraw()

    def set_sort(self, key, rev):
        pass

    # ---- data
    def set_items(self, items, keep=()):
        pos = self.cv.yview()[0]
        self.items = items
        self.sel = {i for i, it in enumerate(items) if it[2] in keep}
        self._layout()
        if keep:
            self.cv.yview_moveto(pos)

    def selected(self):
        return [self.items[i] for i in sorted(self.sel) if i < len(self.items)]

    def focus_first(self):
        self.cv.focus_set()
        if self.items:
            self.sel, self.anchor = {0}, 0
            self.redraw()
            self.app.selection_changed()

    # ---- layout / scrolling
    def _layout(self):
        w = max(self.cv.winfo_width(), 100)
        self.cols = max(1, (w - 8) // self.tw)
        rows = -(-len(self.items) // self.cols)
        self.cv.configure(scrollregion=(0, 0, w, rows * self.th + 12))
        self.redraw()

    def _yview(self, *a):
        self.cv.yview(*a)

    def _on_scroll(self, lo, hi):
        self.sb.set(lo, hi)
        self.redraw()

    def _wheel(self, d):
        self.cv.yview_scroll(d * 2, "units")

    def _rrect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    def redraw(self):
        if not self.alive:
            return
        cv = self.cv
        cv.delete("all")
        n = len(self.items)
        if not n:
            return
        S, tw, th, cols = self.S, self.tw, self.th, self.cols
        y0 = cv.canvasy(0)
        h = cv.winfo_height()
        first = max(0, int(y0 // th) - 0)
        last = int((y0 + h) // th) + 1
        dark = theme.is_dark()
        fg = "#FFFFFF" if dark else "#1A1A1A"
        selbg = "#0A4A7C" if dark else "#CCE4F7"
        fs = 9 if S <= 96 else 10 if S <= 160 else 11
        cats = self.app.cats
        for i in range(first * cols, min(n, (last + 1) * cols)):
            it = self.items[i]
            x, y = 4 + (i % cols) * tw, 4 + (i // cols) * th
            if i in self.sel:
                self._rrect(x, y, x + tw - 6, y + th - 6, 10, fill=selbg, outline=THEME["accent"])
            cx, cy = x + (tw - 6) / 2, y + 8 + S / 2
            photo = self.cache.get(it[2])
            if photo:
                self.cache.move_to_end(it[2])
                cv.create_image(cx, cy, image=photo)
            else:
                self._badge(it, cx, cy, S, cats)
                if it[6] in THUMB_EXT and not it[3] and it[2] not in self.cache and it[2] not in self.pending:
                    self.pending.add(it[2])
                    self.pool.submit(self._load, it[2], S)
            name = it[0] if len(it[0]) <= 46 else it[0][:43] + "…"
            cv.create_text(cx, y + S + 18, text=name, anchor="n", width=tw - 16, fill=fg,
                           font=(FONT, fs), justify="center")

    def _badge(self, it, cx, cy, S, cats):
        cv = self.cv
        if it[3]:   # folder
            w, h = S * 0.78, S * 0.56
            cv.create_rectangle(cx - w / 2, cy - h / 2 - S * 0.07, cx - w * 0.08, cy - h / 2 + S * 0.05, fill="#E8B339", outline="")
            self._rrect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, S * 0.06, fill="#F2C14E", outline="")
            return
        kind = kind_of(it[6], False, cats)
        col = CAT_COLOR.get(kind, CAT_COLOR["Other"])
        w, h = S * 0.58, S * 0.76
        self._rrect(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2, S * 0.07, fill=col, outline="")
        cv.create_polygon(cx + w / 2 - S * 0.18, cy - h / 2, cx + w / 2, cy - h / 2 + S * 0.18,
                          cx + w / 2 - S * 0.18, cy - h / 2 + S * 0.18, fill="#FFFFFF", stipple="gray50", outline="")
        label = (it[6][1:5] or "FILE").upper()
        cv.create_text(cx, cy + h * 0.12, text=label, fill="white", font=(FONT, max(8, int(S * 0.15)), "bold"))

    # ---- thumbnails
    def _load(self, path, S):
        try:
            self.q.put((path, get_thumbnail(path, S)))
        except Exception:
            self.q.put((path, None))

    def _drain(self):
        if not self.alive:
            return
        got = False
        for _ in range(25):
            try:
                path, im = self.q.get_nowait()
            except queue.Empty:
                break
            self.pending.discard(path)
            self.cache[path] = ImageTk.PhotoImage(im) if im is not None else False
            if len(self.cache) > 450:
                self.cache.popitem(last=False)
            got = got or im is not None
        if got:
            self.redraw()
        self.after(80, self._drain)

    # ---- interaction
    def _hit(self, e):
        x, y = e.x - 4, self.cv.canvasy(e.y) - 4
        if x < 0 or y < 0:
            return None
        c, r = int(x // self.tw), int(y // self.th)
        if c >= self.cols:
            return None
        i = r * self.cols + c
        return i if i < len(self.items) else None

    def _click(self, e, ctrl=False, shift=False):
        self.cv.focus_set()
        i = self._hit(e)
        if i is None:
            if not (ctrl or shift):
                self.sel = set()
        elif shift and self.anchor is not None:
            a, b = sorted((self.anchor, i))
            self.sel = set(range(a, b + 1))
        elif ctrl:
            self.sel ^= {i}
            self.anchor = i
        else:
            self.sel, self.anchor = {i}, i
        self.redraw()
        self.app.selection_changed()

    def _ctx(self, e):
        i = self._hit(e)
        if i is None:
            return
        if i not in self.sel:
            self.sel, self.anchor = {i}, i
            self.redraw()
            self.app.selection_changed()
        self.app.show_context(e.x_root, e.y_root)

    def _all(self):
        self.sel = set(range(len(self.items)))
        self.redraw()
        self.app.selection_changed()

    def _move(self, d):
        if not self.items:
            return
        cur = self.anchor if self.anchor is not None else -1
        step = {"up": -self.cols, "down": self.cols}.get(d, d)
        i = min(max(cur + step, 0), len(self.items) - 1)
        self.sel, self.anchor = {i}, i
        y = 4 + (i // self.cols) * self.th
        top, h = self.cv.canvasy(0), self.cv.winfo_height()
        total = max(1, -(-len(self.items) // self.cols) * self.th + 12)
        if y < top:
            self.cv.yview_moveto(max(0, y - 4) / total)
        elif y + self.th > top + h:
            self.cv.yview_moveto(max(0, y + self.th - h + 4) / total)
        self.redraw()
        self.app.selection_changed()
