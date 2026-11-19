"""Windows 11 look: colours and widget styling shared by all windows."""
import platform
import tkinter as tk
from tkinter import ttk
import customtkinter as ctk

IS_WIN = platform.system() == "Windows"
FONT = "Segoe UI Variable Text" if IS_WIN else "Segoe UI"

THEME = {   # (light, dark)
    "bg": ("#F3F3F3", "#202020"),
    "card": ("#FFFFFF", "#2B2B2B"),
    "stroke": ("#E5E5E5", "#3A3A3A"),
    "text": ("#1A1A1A", "#FFFFFF"),
    "sub": ("#616161", "#A0A0A0"),
    "hover": ("#EAEAEA", "#383838"),
    "accent": "#0067C0",
    "danger": "#C42B1C",
}


def is_dark():
    return ctk.get_appearance_mode() == "Dark"


def pick(key):
    v = THEME[key]
    return v[1] if is_dark() else v[0] if isinstance(v, tuple) else v


def style_tree(style_name="Fluent.Treeview", row=32):
    dark = is_dark()
    bg, fg = ("#2B2B2B", "#FFFFFF") if dark else ("#FFFFFF", "#1A1A1A")
    sel = "#0A4A7C" if dark else "#CCE4F7"
    st = ttk.Style()
    st.theme_use("clam")
    st.configure(style_name, background=bg, fieldbackground=bg, foreground=fg, rowheight=row,
                 borderwidth=0, font=(FONT, 11))
    st.map(style_name, background=[("selected", sel)], foreground=[("selected", fg)])
    st.configure(style_name + ".Heading", background=bg, foreground="#8A8A8A", relief="flat",
                 font=(FONT, 10, "bold"), padding=(8, 6))
    st.map(style_name + ".Heading", background=[("active", bg)])
    st.layout(style_name, [("Treeview.treearea", {"sticky": "nswe"})])


def style_menu(m):
    dark = is_dark()
    m.configure(bg="#2B2B2B" if dark else "#FFFFFF", fg="#FFFFFF" if dark else "#1A1A1A",
                activebackground=THEME["accent"], activeforeground="white", relief="flat", bd=0,
                font=(FONT, 11), selectcolor=THEME["accent"])


def win11_titlebar(window):
    if not IS_WIN:
        return
    try:
        import ctypes
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        dark = 1 if is_dark() else 0
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(ctypes.c_int(dark)), 4)
        bg = 0x202020 if dark else 0xF3F3F3
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(ctypes.c_int(bg)), 4)
    except Exception:
        pass
