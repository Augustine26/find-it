"""Result views: Details list and Thumbnail grid (small / medium / large / extra large)."""
import os, queue
import tkinter.font as tkfont
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import tkinter as tk
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


class VirtualDetails(ctk.CTkFrame):
    """Details list that only draws the rows you can see - instant even with 100,000+ results."""
    COLS = (("name", "Name", 270, True), ("path", "Location", 270, True), ("size", "Size", 80, False),
            ("type", "Type", 84, False), ("date", "Modified", 128, False), ("created", "Created", 128, False))
    ROW, HEAD = 34, 38

    def __init__(self, master, app):
        super().__init__(master, fg_color="transparent")
        self.app = app
        self.items, self.sel, self.anchor = [], set(), None
        self.sort = ("name", False)
        saved = app.settings["col_widths"] or {}
        self.w = {k: int(saved.get(k, w)) for k, _t, w, _f in self.COLS}
        self.font = tkfont.Font(family=FONT, size=10)
        self.bold = tkfont.Font(family=FONT, size=9, weight="bold")
        self.cw = max(5, self.font.measure("n"))
        self.empty_text = ""
        self._drag = None
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)
        self.hd = tk.Canvas(self, height=self.HEAD, highlightthickness=0, bd=0)
        self.cv = tk.Canvas(self, highlightthickness=0, bd=0, yscrollincrement=self.ROW)
        self.sb = ctk.CTkScrollbar(self, command=self.cv.yview)
        self.cv.configure(yscrollcommand=self._on_scroll)
        self.hd.grid(row=0, column=0, sticky="ew", padx=(8, 0), pady=(6, 0))
        self.cv.grid(row=1, column=0, sticky="nsew", padx=(8, 0), pady=(0, 6))
        self.sb.grid(row=1, column=1, sticky="ns", pady=(0, 6), padx=(0, 4))
        cv, hd = self.cv, self.hd
        cv.bind("<Configure>", lambda e: self._layout())
        cv.bind("<Button-1>", self._click)
        cv.bind("<Control-Button-1>", lambda e: self._click(e, ctrl=True))
        cv.bind("<Shift-Button-1>", lambda e: self._click(e, shift=True))
        cv.bind("<Double-1>", self._dbl)
        cv.bind("<Button-3>", self._ctx)
        cv.bind("<MouseWheel>", lambda e: self._wheel(-1 if e.delta > 0 else 1))
        cv.bind("<Button-4>", lambda e: self._wheel(-1))
        cv.bind("<Button-5>", lambda e: self._wheel(1))
        for k, d in (("Up", -1), ("Down", 1), ("Prior", -10), ("Next", 10)):
            cv.bind(f"<{k}>", lambda e, d=d: self._move(d))
            cv.bind(f"<Shift-{k}>", lambda e, d=d: self._move(d, True))
        cv.bind("<Home>", lambda e: self._move(-10 ** 9))
        cv.bind("<End>", lambda e: self._move(10 ** 9))
        cv.bind("<Return>", lambda e: app.open_selected())
        cv.bind("<Control-a>", lambda e: self._all())
        cv.bind("<Control-c>", lambda e: app.copy_path())
        cv.bind("<Delete>", lambda e: app.delete_selected())
        cv.bind("<F2>", lambda e: app.rename_selected())
        cv.bind("<Alt-Return>", lambda e: app.properties_selected())
        hd.bind("<Motion>", self._hd_motion)
        hd.bind("<Button-1>", self._hd_down)
        hd.bind("<B1-Motion>", self._hd_drag)
        hd.bind("<ButtonRelease-1>", self._hd_up)
        hd.bind("<Configure>", lambda e: self._draw_head())
        self.restyle()

    # ---- look
    def restyle(self):
        c = theme.pick("card")
        self.cv.configure(bg=c)
        self.hd.configure(bg=c)
        self._draw_head()
        self.redraw()

    def set_sort(self, key, rev):
        self.sort = (key, rev)
        self._draw_head()

    def _geom(self):
        W = max(self.cv.winfo_width(), 300)
        left = 12
        avail = W - left - 8
        fixed = sum(self.w[k] for k, _t, _w, f in self.COLS if not f)
        base = sum(self.w[k] for k, _t, _w, f in self.COLS if f)
        scale = max(avail - fixed, 160) / base
        xs, ws, x = {}, {}, left
        for k, _t, _w, f in self.COLS:
            wk = max(80, int(self.w[k] * scale)) if f else self.w[k]
            xs[k], ws[k] = x, wk
            x += wk
        return xs, ws, scale

    def _draw_head(self):
        hd = self.hd
        hd.delete("all")
        xs, ws, _ = self._geom()
        sub, stroke = theme.pick("sub"), theme.pick("hover")
        key, rev = self.sort
        for k, title, _w, _f in self.COLS:
            arrow = (" ▼" if rev else " ▲") if k == key else ""
            hd.create_text(xs[k] + (44 if k == "name" else 10), self.HEAD // 2, text=title + arrow, anchor="w",
                           fill=theme.pick("text") if k == key else sub, font=self.bold)
            if k != "created":
                hd.create_line(xs[k] + ws[k], 9, xs[k] + ws[k], self.HEAD - 9, fill=stroke)
        hd.create_line(0, self.HEAD - 1, 4000, self.HEAD - 1, fill=stroke)

    # ---- header interaction (sort / resize)
    def _edge(self, x):
        xs, ws, _ = self._geom()
        for k, _t, _w, _f in self.COLS:
            if abs(x - (xs[k] + ws[k])) <= 4:
                return k
        return None

    def _hd_motion(self, e):
        self.hd.configure(cursor="sb_h_double_arrow" if self._edge(e.x) else "")

    def _hd_down(self, e):
        k = self._edge(e.x)
        if k:
            _xs, _ws, scale = self._geom()
            flex = next(f for kk, _t, _w, f in self.COLS if kk == k)
            self._drag = (k, e.x, self.w[k], scale if flex else 1.0)
            return
        xs, ws, _ = self._geom()
        for k, _t, _w, _f in self.COLS:
            if xs[k] <= e.x < xs[k] + ws[k]:
                self.app.sort_by(k)
                return

    def _hd_drag(self, e):
        if self._drag:
            k, x0, w0, scale = self._drag
            self.w[k] = max(50, int(w0 + (e.x - x0) / scale))
            self._draw_head()
            self.redraw()

    def _hd_up(self, e):
        if self._drag:
            self._drag = None
            self.app.settings["col_widths"] = dict(self.w)
            self.app.settings.save()

    # ---- data
    def set_items(self, items, keep=()):
        pos = self.cv.yview()[0]
        self.items = items
        self.sel = {i for i, it in enumerate(items) if it[2] in keep} if keep else set()
        self.cv.configure(scrollregion=(0, 0, max(self.cv.winfo_width(), 100), max(len(items) * self.ROW, 1)))
        if keep:
            self.cv.yview_moveto(pos)
        else:
            self.cv.yview_moveto(0)
        self.redraw()

    def selected(self):
        return [self.items[i] for i in sorted(self.sel) if i < len(self.items)]

    def focus_first(self):
        self.cv.focus_set()
        if self.items:
            self.sel, self.anchor = {0}, 0
            self.cv.yview_moveto(0)
            self.redraw()
            self.app.selection_changed()

    # ---- drawing
    def _layout(self):
        self.cv.configure(scrollregion=(0, 0, max(self.cv.winfo_width(), 100), max(len(self.items) * self.ROW, 1)))
        self._draw_head()
        self.redraw()

    def _on_scroll(self, lo, hi):
        self.sb.set(lo, hi)
        self.redraw()

    def _wheel(self, d):
        self.cv.yview_scroll(d * 3, "units")

    def _rrect(self, x1, y1, x2, y2, r, **kw):
        pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
               x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
        return self.cv.create_polygon(pts, smooth=True, **kw)

    def _fit(self, text, px, tail=False):
        mx = max(1, int(px / self.cw))
        if len(text) <= mx:
            return text
        return ("…" + text[-(mx - 1):]) if tail else (text[:mx - 1] + "…")

    def redraw(self):
        cv = self.cv
        cv.delete("all")
        n = len(self.items)
        W, H = max(cv.winfo_width(), 100), max(cv.winfo_height(), 50)
        text_c, sub_c, soft, acc = theme.pick("text"), theme.pick("sub"), theme.pick("soft"), THEME["accent"]
        if not n:
            y0 = cv.canvasy(0)
            cv.create_text(W / 2, y0 + H / 2 - 10, text=self.empty_text or "No results", fill=sub_c, font=(FONT, 13))
            return
        R = self.ROW
        y0 = cv.canvasy(0)
        first, last = max(0, int(y0 // R)), min(n, int((y0 + H) // R) + 2)
        xs, ws, _ = self._geom()
        terms = getattr(self.app, "highlight", [])
        cats = self.app.cats
        mark = theme.pick("mark")
        for i in range(first, last):
            name, ln, path, is_dir, size, mt, ext, ct = self.items[i]
            y, cy = i * R, i * R + R / 2
            if i in self.sel:
                self._rrect(6, y + 2, W - 8, y + R - 2, 9, fill=soft, outline="")
                self._rrect(8, y + 9, 11, y + R - 9, 1, fill=acc, outline="")
            x0 = xs["name"] + 14
            if is_dir:
                cv.create_rectangle(x0, cy - 8, x0 + 9, cy - 4, fill="#E8B339", outline="")
                self._rrect(x0, cy - 6, x0 + 21, cy + 8, 3, fill="#F2C14E", outline="")
            else:
                col = CAT_COLOR.get(kind_of(ext, False, cats), CAT_COLOR["Other"])
                self._rrect(x0 + 3, cy - 9, x0 + 18, cy + 9, 3, fill=col, outline="")
                cv.create_polygon(x0 + 12, cy - 9, x0 + 18, cy - 3, x0 + 12, cy - 3, fill="#FFFFFF", stipple="gray50", outline="")
            tx = x0 + 30
            shown = self._fit(name, ws["name"] - 52)
            for t in terms[:2]:
                j = ln.find(t)
                if 0 <= j and j + len(t) <= len(shown):
                    a = tx + self.font.measure(shown[:j])
                    b = a + self.font.measure(shown[j:j + len(t)])
                    cv.create_rectangle(a - 1, cy - 10, b + 1, cy + 10, fill=mark, outline="")
                    break
            cv.create_text(tx, cy, text=shown, anchor="w", fill=text_c, font=self.font)
            cv.create_text(xs["path"] + 10, cy, text=self._fit(os.path.dirname(path), ws["path"] - 18, True),
                           anchor="w", fill=sub_c, font=self.font)
            cv.create_text(xs["size"] + ws["size"] - 12, cy, text="" if is_dir else human_size(size), anchor="e",
                           fill=text_c, font=self.font)
            cv.create_text(xs["type"] + 10, cy, text=self._fit(type_name(ext, is_dir), ws["type"] - 14),
                           anchor="w", fill=sub_c, font=self.font)
            cv.create_text(xs["date"] + 10, cy, text=human_date(mt), anchor="w", fill=sub_c, font=self.font)
            cv.create_text(xs["created"] + 10, cy, text=human_date(ct), anchor="w", fill=sub_c, font=self.font)

    # ---- interaction
    def _hit(self, e):
        i = int(self.cv.canvasy(e.y) // self.ROW)
        return i if 0 <= i < len(self.items) else None

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

    def _dbl(self, e):
        if self._hit(e) is not None:
            self.app.open_selected()

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

    def _move(self, d, extend=False):
        n = len(self.items)
        if not n:
            return
        cur = self.anchor if self.anchor is not None else (0 if d > 0 else n - 1)
        if self.anchor is None and abs(d) == 1:
            i = 0 if d > 0 else n - 1
        else:
            i = min(max(cur + d, 0), n - 1)
        if extend and self.anchor is not None:
            a, b = sorted((self.anchor, i))
            self.sel = set(range(a, b + 1))
            self._cursor = i
        else:
            self.sel, self.anchor = {i}, i
        y, top, h = i * self.ROW, self.cv.canvasy(0), self.cv.winfo_height()
        total = max(1, n * self.ROW)
        if y < top:
            self.cv.yview_moveto(y / total)
        elif y + self.ROW > top + h:
            self.cv.yview_moveto((y + self.ROW - h) / total)
        self.redraw()
        self.app.selection_changed()


class LiteScroll(tk.Frame):
    """Light scrolling list (used for the side panel) - much cheaper than CTkScrollableFrame."""

    def __init__(self, master, **kw):
        super().__init__(master, bd=0, highlightthickness=0)
        self.cv = tk.Canvas(self, highlightthickness=0, bd=0)
        self.inner = tk.Frame(self.cv, bd=0, highlightthickness=0)
        self.win = self.cv.create_window(0, 0, window=self.inner, anchor="nw")
        self.sb = ctk.CTkScrollbar(self, command=self.cv.yview, width=10)
        self.cv.configure(yscrollcommand=self.sb.set)
        self.cv.pack(side="left", fill="both", expand=True)
        self.inner.bind("<Configure>", self._inner)
        self.cv.bind("<Configure>", lambda e: self.cv.itemconfigure(self.win, width=e.width))
        self.cv.bind("<Enter>", lambda e: self._bind_wheel(True))
        self.cv.bind("<Leave>", lambda e: self._bind_wheel(False))
        self.inner.bind("<Enter>", lambda e: self._bind_wheel(True))
        self.inner.bind("<Leave>", lambda e: self._bind_wheel(False))
        self.restyle()

    def restyle(self):
        c = theme.pick("card")
        for w in (self, self.cv, self.inner):
            w.configure(bg=c)

    def _inner(self, e):
        self.cv.configure(scrollregion=self.cv.bbox("all"))
        need = self.inner.winfo_reqheight() > self.cv.winfo_height()
        if need and not self.sb.winfo_ismapped():
            self.sb.pack(side="right", fill="y")
        elif not need and self.sb.winfo_ismapped():
            self.sb.pack_forget()

    def _bind_wheel(self, on):
        if on:
            self.bind_all("<MouseWheel>", self._wheel)
            self.bind_all("<Button-4>", lambda e: self.cv.yview_scroll(-2, "units"))
            self.bind_all("<Button-5>", lambda e: self.cv.yview_scroll(2, "units"))
        else:
            self.unbind_all("<MouseWheel>")
            self.unbind_all("<Button-4>")
            self.unbind_all("<Button-5>")

    def _wheel(self, e):
        if self.inner.winfo_reqheight() > self.cv.winfo_height():
            self.cv.yview_scroll(-2 if e.delta > 0 else 2, "units")

    def clear(self):
        for w in self.inner.winfo_children():
            w.destroy()
        self.cv.yview_moveto(0)

    def header(self, text, action=None):
        card, sub = theme.pick("card"), theme.pick("sub")
        r = tk.Frame(self.inner, bg=card)
        r.pack(fill="x", pady=(14, 2), padx=6)
        tk.Label(r, text=text.upper(), bg=card, fg=sub, font=(FONT, 8, "bold"), anchor="w").pack(side="left", padx=4)
        if action:
            b = tk.Label(r, text=action[0], bg=card, fg=THEME["accent"], font=(FONT, 9), cursor="hand2")
            b.pack(side="right", padx=4)
            b.bind("<Button-1>", lambda e: action[1]())

    def row(self, text, cmd, rclick=None):
        card, hov, fg = theme.pick("card"), theme.pick("hover"), theme.pick("text")
        l = tk.Label(self.inner, text=text, bg=card, fg=fg, font=(FONT, 10), anchor="w", padx=12, pady=6, cursor="hand2")
        l.pack(fill="x", padx=4, pady=1)
        l.bind("<Enter>", lambda e: l.configure(bg=hov))
        l.bind("<Leave>", lambda e: l.configure(bg=card))
        l.bind("<Button-1>", lambda e: cmd())
        if rclick:
            l.bind("<Button-3>", rclick)
        return l

    def note(self, text):
        tk.Label(self.inner, text=text, bg=theme.pick("card"), fg=theme.pick("sub"), font=(FONT, 9), anchor="w",
                 padx=12, wraplength=170, justify="left").pack(fill="x")


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
        self.cv.grid(row=0, column=0, sticky="nsew", padx=(8, 0), pady=8)
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
        self.cv.configure(bg=theme.pick("card"))
        self.redraw()

    def set_sort(self, key, rev):
        pass

    empty_text = ""

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
            cv.create_text(max(cv.winfo_width(), 100) / 2, cv.canvasy(0) + max(cv.winfo_height(), 50) / 2 - 10,
                           text=self.empty_text or "No results", fill=theme.pick("sub"), font=(FONT, 13))
            return
        S, tw, th, cols = self.S, self.tw, self.th, self.cols
        y0 = cv.canvasy(0)
        h = cv.winfo_height()
        first = max(0, int(y0 // th) - 0)
        last = int((y0 + h) // th) + 1
        dark = theme.is_dark()
        fg = theme.pick("text")
        selbg = theme.pick("soft")
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
