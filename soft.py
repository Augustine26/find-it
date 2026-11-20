"""Soft / neumorphic widgets: raised and pressed-in shapes drawn with light + dark shadows (Pillow)."""
import weakref
import tkinter as tk
import tkinter.font as tkfont
import customtkinter as ctk
from PIL import Image, ImageDraw, ImageFilter, ImageChops, ImageTk
import theme
from theme import FONT, pick

_cache = {}
_registry = weakref.WeakSet()


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def scale_of(widget):
    try:
        return float(ctk.ScalingTracker.get_widget_scaling(widget))
    except Exception:
        return 1.0


def render(kind, w, h, radius, pad, depth, fill=None):
    """w x h picture of a shape inset by pad. kind: 'raised' | 'inset'. fill: None (surface) or (c1, c2) gradient."""
    w, h = max(int(w), 4), max(int(h), 4)
    radius, pad, depth = int(round(radius)), int(pad), max(1, int(round(depth)))
    surface, hi, sh = _rgb(pick("bg")), _rgb(pick("hi")), _rgb(pick("sh"))
    key = (kind, w, h, int(radius), int(pad), int(depth), fill, surface, hi, sh)
    if key in _cache:
        return _cache[key]
    ss = 4 if w * h < 160000 else 2
    big = Image.new("L", (w * ss, h * ss), 0)
    box = (pad * ss, pad * ss, (w - pad) * ss - 1, (h - pad) * ss - 1)
    ImageDraw.Draw(big).rounded_rectangle(box, radius * ss, fill=255)
    shape = big.resize((w, h), Image.LANCZOS)
    blur = max(1.0, depth * 0.85)
    base = Image.new("RGB", (w, h), surface)
    if kind == "raised":
        dark = ImageChops.offset(shape, depth, depth).filter(ImageFilter.GaussianBlur(blur))
        light = ImageChops.offset(shape, -depth, -depth).filter(ImageFilter.GaussianBlur(blur))
        base = Image.composite(Image.new("RGB", (w, h), sh), base, dark.point(lambda v: int(v * 0.95)))
        base = Image.composite(Image.new("RGB", (w, h), hi), base, light.point(lambda v: int(v * 1.0)))
        if fill:
            c1, c2 = _rgb(fill[0]), _rgb(fill[1])
            grad = Image.linear_gradient("L").rotate(45, resample=Image.BICUBIC, expand=False).resize((w, h))
            body = Image.composite(Image.new("RGB", (w, h), c2), Image.new("RGB", (w, h), c1), grad)
        else:
            body = Image.new("RGB", (w, h), surface)
        base = Image.composite(body, base, shape)
    else:
        outside = ImageChops.invert(shape)
        dark = ImageChops.multiply(ImageChops.offset(outside, depth, depth).filter(ImageFilter.GaussianBlur(blur)), shape)
        light = ImageChops.multiply(ImageChops.offset(outside, -depth, -depth).filter(ImageFilter.GaussianBlur(blur)), shape)
        base = Image.composite(Image.new("RGB", (w, h), sh), base, dark.point(lambda v: int(v * 0.9)))
        base = Image.composite(Image.new("RGB", (w, h), hi), base, light.point(lambda v: int(v * 0.9)))
    if len(_cache) > 300:
        _cache.clear()
    _cache[key] = base
    return base


class SoftFrame(tk.Frame):
    """Panel with a raised (or pressed-in) soft shadow. Put content in .body"""

    def __init__(self, master, kind="raised", radius=22, pad=16, depth=7, inner=None, **kw):
        super().__init__(master, bg=pick("bg"), bd=0, highlightthickness=0, **kw)
        self.kind, self.r, self.pad0, self.depth0 = kind, radius, pad, depth
        s = scale_of(self)
        self.pad = int(pad * s)
        if inner is None:     # keep content clear of the rounded corners (and of the inner shadow when pressed-in)
            ix = iy = self.pad + int((0.3 * radius + (depth * 1.6 if kind == "inset" else 0)) * s)
        else:
            ix, iy = int(inner[0] * s), int(inner[1] * s)
        self.lbl = tk.Label(self, bd=0, bg=pick("bg"))
        self.lbl.place(x=0, y=0, relwidth=1, relheight=1)
        self.body = tk.Frame(self, bg=pick("bg"), bd=0, highlightthickness=0)
        self.body.pack(fill="both", expand=True, padx=ix, pady=iy)
        self._size, self._job, self._photo = (0, 0), None, None
        self.bind("<Configure>", self._cfg)
        _registry.add(self)

    def _cfg(self, e):
        if (e.width, e.height) == self._size:
            return
        self._size = (e.width, e.height)
        if self._job:
            self.after_cancel(self._job)
        self._job = self.after(10 if e.width * e.height < 100000 else 90, self.draw)

    def draw(self):
        self._job = None
        w, h = self._size
        if w < 10 or h < 10:
            return
        s = scale_of(self)
        img = render(self.kind, w, h, self.r * s, self.pad, self.depth0 * s)
        self._photo = ImageTk.PhotoImage(img)
        self.lbl.configure(image=self._photo)

    def restyle(self):
        bg = pick("bg")
        for w in (self, self.lbl, self.body):
            w.configure(bg=bg)
        self.draw()


class SoftButton(tk.Canvas):
    """Round / pill button: raised, pressed-in while clicked, optional blue gradient (primary)."""

    def __init__(self, master, text="", command=None, width=44, height=44, variant="raised",
                 font_size=12, bold=False, depth=4):
        s = scale_of(master)
        self.pad = int((depth + 4) * s)
        self.vw, self.vh = int(width * s), int(height * s)
        super().__init__(master, width=self.vw + 2 * self.pad, height=self.vh + 2 * self.pad, bg=pick("bg"),
                         highlightthickness=0, bd=0, cursor="hand2")
        self.text, self.command, self.variant, self.depth = text, command, variant, depth * s
        self.font = (FONT, font_size, "bold" if bold else "normal")
        self.state, self._photo = "normal", None
        self.bind("<Enter>", lambda e: self._set("hover"))
        self.bind("<Leave>", lambda e: self._set("normal"))
        self.bind("<ButtonPress-1>", lambda e: self._set("press"))
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Configure>", lambda e: self.draw())
        _registry.add(self)
        self.draw()

    def _set(self, st):
        if st != self.state:
            self.state = st
            self.draw()

    def _release(self, e):
        inside = 0 <= e.x < self.winfo_width() and 0 <= e.y < self.winfo_height()
        self._set("hover" if inside else "normal")
        if inside and self.command:
            self.command()

    def configure_button(self, text=None, variant=None):
        if text is not None:
            self.text = text
        if variant is not None:
            self.variant = variant
        self.draw()

    def draw(self):
        w, h = self.vw + 2 * self.pad, self.vh + 2 * self.pad
        primary = self.variant == "primary"
        fill = (theme.THEME["accent2"], theme.THEME["accent"]) if primary else None
        kind = "inset" if (self.state == "press" and not primary) or self.variant == "inset" else "raised"
        r = min(self.vw, self.vh) / 2 if self.vh <= self.vw else self.vh / 2
        img = render(kind, w, h, r, self.pad, self.depth if kind == "raised" else self.depth * 0.8, fill)
        self._photo = ImageTk.PhotoImage(img)
        self.delete("all")
        self.configure(bg=pick("bg"))
        self.create_image(0, 0, image=self._photo, anchor="nw")
        if primary:
            col = "#FFFFFF"
        elif self.state == "hover" or self.variant == "inset":
            col = theme.THEME["accent"]
        else:
            col = pick("text")
        dy = 1 if self.state == "press" else 0
        self.create_text(w / 2, h / 2 + dy, text=self.text, fill=col, font=self.font)

    restyle = draw


class Chips(tk.Frame):
    """Row of pill buttons (filter chips); the selected one is the blue gradient button."""

    def __init__(self, master, values, command):
        super().__init__(master, bg=pick("bg"), bd=0, highlightthickness=0)
        self.values, self.command, self.current, self.btns = list(values), command, None, {}
        f = tkfont.Font(family=FONT, size=11)
        for v in self.values:
            wpx = f.measure(v) + 30
            b = SoftButton(self, v, lambda v=v: self._pick(v), width=wpx, height=34, variant="raised",
                           font_size=11, depth=3)
            b.pack(side="left", padx=1)
            self.btns[v] = b

    def _pick(self, v):
        self.set(v)
        self.command(v)

    def set(self, v):
        self.current = v
        for k, b in self.btns.items():
            b.configure_button(variant="primary" if k == v else "raised")

    def get(self):
        return self.current

    def cget(self, key):
        return self.values if key == "values" else None

    def restyle(self):
        self.configure(bg=pick("bg"))


class SoftEntry(SoftFrame):
    """Pressed-in pill containing a text entry."""

    def __init__(self, master, placeholder="", font_size=14, height=40):
        super().__init__(master, kind="inset", radius=23, pad=10, depth=5, inner=(28, 19))
        self.entry = ctk.CTkEntry(self.body, height=30, corner_radius=0, border_width=0, fg_color=theme.THEME["bg"],
                                  bg_color=theme.THEME["bg"], text_color=theme.THEME["text"],
                                  placeholder_text=placeholder, font=(FONT, font_size))
        self.entry.pack(fill="x")


def restyle_all():
    for w in list(_registry):
        try:
            w.restyle()
        except Exception:
            pass
