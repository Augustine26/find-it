"""Windows 11 glass look: colours, white strokes, acrylic / mica backdrop, shared widget styling."""
import sys
import platform
import customtkinter as ctk
from tkinter import ttk

IS_WIN = platform.system() == "Windows"
FONT = "Segoe UI Variable Text" if IS_WIN else "Segoe UI"
KEY = "#010203"            # colour that becomes see-through when the glass effect is on
RADIUS = 16

PALETTES = {
    # soft / neumorphic: surface, panels and page share one colour; depth comes from light + dark shadows
    "soft": {
        "bg": ("#E7EBEF", "#2A2E35"), "card": ("#E7EBEF", "#2A2E35"),
        "stroke": ("#D2D8E0", "#3B404B"), "text": ("#1F2937", "#E8EAF0"), "sub": ("#6B7280", "#98A0AE"),
        "hover": ("#DCE1E8", "#343944"), "soft": ("#D3E2F6", "#27405F"), "mark": ("#FFE9A6", "#5E4F14"),
        "hi": ("#FFFFFF", "#3A3F4B"), "sh": ("#B7C0CE", "#1B1E23"),
        "accent": "#0072FF", "accent_hover": "#0060D6", "accent2": "#00C6FF", "danger": "#C42B1C",
    },
    "glass": {
        "bg": ("#E8ECF4", "#17181C"), "card": ("#FAFBFE", "#25262C"),
        "stroke": ("#FFFFFF", "#6E7080"), "text": ("#1B1D23", "#F4F5F8"), "sub": ("#5E6472", "#A4A8B5"),
        "hover": ("#E3E8F2", "#363842"), "soft": ("#DCEAFB", "#203A5A"), "mark": ("#FFE9A6", "#5E4F14"),
        "hi": ("#FFFFFF", "#3A3F4B"), "sh": ("#B7C0CE", "#1B1E23"),
        "accent": "#0A64D8", "accent_hover": "#0853B3", "accent2": "#00A3FF", "danger": "#C42B1C",
    },
}
THEME = dict(PALETTES["soft"])
STYLE = "soft"


def set_style(name):
    """choose 'soft' or 'glass' (before any window is created); THEME is updated in place"""
    global STYLE
    STYLE = name if name in PALETTES else "soft"
    THEME.clear()
    THEME.update(PALETTES[STYLE])


def hex_bgr(h):
    h = h.lstrip("#")
    return int(h[4:6] + h[2:4] + h[0:2], 16)


_glass = {"on": False}


def is_dark():
    return ctk.get_appearance_mode() == "Dark"


def pick(key):
    v = THEME[key]
    return (v[1] if is_dark() else v[0]) if isinstance(v, tuple) else v


def root_bg(settings=None):
    glass = STYLE == "glass" and IS_WIN and settings is not None and settings["glass"] != "off"
    return KEY if glass else THEME["bg"]


def panel_kw(radius=RADIUS):
    """frosted panel: light fill, rounded, 1px white stroke"""
    return dict(fg_color=THEME["card"], corner_radius=radius, border_width=1, border_color=THEME["stroke"])


def style_tree(style_name="Fluent.Treeview", row=32):
    dark = is_dark()
    bg, fg = pick("card"), pick("text")
    sel = pick("soft")
    st = ttk.Style()
    st.theme_use("clam")
    st.configure(style_name, background=bg, fieldbackground=bg, foreground=fg, rowheight=row,
                 borderwidth=0, font=(FONT, 11))
    st.map(style_name, background=[("selected", sel)], foreground=[("selected", fg)])
    st.configure(style_name + ".Heading", background=bg, foreground=pick("sub"), relief="flat",
                 font=(FONT, 10, "bold"), padding=(8, 6))
    st.map(style_name + ".Heading", background=[("active", bg)])
    st.layout(style_name, [("Treeview.treearea", {"sticky": "nswe"})])
    return dark


def style_menu(m):
    m.configure(bg=pick("card"), fg=pick("text"), activebackground=THEME["accent"], activeforeground="white",
                relief="flat", bd=0, font=(FONT, 11), selectcolor=THEME["accent"])


def win11_titlebar(window, glass=False):
    """dark/light title bar, tinted to the window (skipped while glass is on)"""
    if not IS_WIN:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        dark = 1 if is_dark() else 0
        dwm = ctypes.windll.dwmapi
        dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(dark)), 4)
        if not glass:
            bg = hex_bgr(pick("bg"))
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(bg)), 4)
    except Exception:
        pass


def apply_glass(win, mode="acrylic", opacity=0.97):
    """Real Windows 11 acrylic/mica behind the window. Returns True when the glass is active.
    The window colour KEY becomes see-through, everything else (panels) stays solid."""
    if not IS_WIN:
        return False
    try:
        import ctypes
        from ctypes import wintypes, byref, c_int, c_uint, sizeof
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        dwm = ctypes.windll.dwmapi

        class MARGINS(ctypes.Structure):
            _fields_ = [("l", c_int), ("r", c_int), ("t", c_int), ("b", c_int)]

        dwm.DwmSetWindowAttribute(hwnd, 20, byref(c_int(1 if is_dark() else 0)), 4)
        build = sys.getwindowsversion().build
        if mode == "off":
            win.attributes("-transparentcolor", "")
            win.attributes("-alpha", 1.0)
            dwm.DwmExtendFrameIntoClientArea(hwnd, byref(MARGINS(0, 0, 0, 0)))
            if build >= 22621:
                dwm.DwmSetWindowAttribute(hwnd, 38, byref(c_int(0)), 4)
            else:
                _accent(hwnd, 0, 0)
            _glass["on"] = False
            win.configure(fg_color=THEME["bg"])
            win11_titlebar(win)
            return False
        win.configure(fg_color=KEY)
        win.attributes("-transparentcolor", KEY)
        win.attributes("-alpha", max(0.6, min(1.0, float(opacity))))
        dwm.DwmExtendFrameIntoClientArea(hwnd, byref(MARGINS(-1, -1, -1, -1)))
        if build >= 22621:
            dwm.DwmSetWindowAttribute(hwnd, 35, byref(c_uint(0xFFFFFFFE)), 4)   # title bar: no own colour
            dwm.DwmSetWindowAttribute(hwnd, 38, byref(c_int(3 if mode == "acrylic" else 2)), 4)
        else:                                                                     # Windows 10 / early 11
            tint = 0x99202020 if is_dark() else 0x99F5F2EE
            _accent(hwnd, 4, tint)
        _glass["on"] = True
        return True
    except Exception:
        try:
            win.attributes("-transparentcolor", "")
            win.configure(fg_color=THEME["bg"])
        except Exception:
            pass
        return False


def _accent(hwnd, state, tint):
    import ctypes
    from ctypes import c_int, c_uint, c_void_p, c_size_t, byref, sizeof, cast

    class ACCENT(ctypes.Structure):
        _fields_ = [("state", c_int), ("flags", c_int), ("color", c_uint), ("anim", c_int)]

    class DATA(ctypes.Structure):
        _fields_ = [("attr", c_int), ("data", c_void_p), ("size", c_size_t)]

    a = ACCENT(state, 2, tint, 0)
    d = DATA(19, cast(byref(a), c_void_p), sizeof(a))
    ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, byref(d))
