"""Windows integration: Explorer right-click menu, startup, admin, tray icon, hotkey, recycle bin."""
import os, sys, subprocess, threading
from engine import IS_WIN, APP_NAME, resource_path, is_admin

NO_WINDOW = 0x08000000 if IS_WIN else 0


def launch_command():
    """command line (list) that starts this app again"""
    if getattr(sys, "frozen", False):
        return [sys.executable]
    main = os.path.join(os.path.dirname(os.path.abspath(__file__)), "findit.py")
    py = sys.executable
    if IS_WIN and py.lower().endswith("python.exe"):
        pw = py[:-10] + "pythonw.exe"
        if os.path.exists(pw):
            py = pw
    return [py, main]


def _quote(parts):
    return " ".join(f'"{p}"' for p in parts)


def new_window(args=()):
    try:
        subprocess.Popen(launch_command() + list(args), close_fds=True)
    except Exception:
        pass


def relaunch_as_admin(args=()):
    """ask Windows for administrator rights and start a new elevated copy. True if it was launched."""
    if not IS_WIN:
        return False
    import ctypes
    cmd = launch_command()
    params = _quote(cmd[1:] + list(args))
    r = ctypes.windll.shell32.ShellExecuteW(None, "runas", cmd[0], params, None, 1)
    return r > 32


# ---- Explorer right-click menu --------------------------------------------------
_MENU_KEYS = [
    (r"Software\Classes\Directory\shell\FindIt", "%1"),
    (r"Software\Classes\Directory\Background\shell\FindIt", "%V"),
    (r"Software\Classes\Drive\shell\FindIt", "%1"),
]


def context_menu_installed():
    if not IS_WIN:
        return False
    import winreg
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CURRENT_USER, _MENU_KEYS[0][0]))
        return True
    except OSError:
        return False


def install_context_menu():
    import winreg
    cmd = launch_command()
    for key, arg in _MENU_KEYS:
        k = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key)
        winreg.SetValueEx(k, None, 0, winreg.REG_SZ, "Search with FindIt")
        winreg.SetValueEx(k, "Icon", 0, winreg.REG_SZ, cmd[0] if getattr(sys, "frozen", False) else resource_path("findit.ico"))
        winreg.CloseKey(k)
        c = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key + r"\command")
        winreg.SetValueEx(c, None, 0, winreg.REG_SZ, f'{_quote(cmd)} --path "{arg}"')
        winreg.CloseKey(c)


def remove_context_menu():
    import winreg
    for key, _ in _MENU_KEYS:
        for sub in (key + r"\command", key):
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, sub)
            except OSError:
                pass


# ---- start with Windows ----------------------------------------------------------
_RUN = r"Software\Microsoft\Windows\CurrentVersion\Run"


def set_startup(enable, elevated=False, minimized=True):
    """Registry Run key normally; a Task Scheduler task (no UAC prompt) when running as admin."""
    if not IS_WIN:
        return False
    import winreg
    cmd = _quote(launch_command()) + (" --background" if minimized else "")
    try:
        k = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN, 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(k, APP_NAME)
        except OSError:
            pass
        subprocess.run(["schtasks", "/Delete", "/F", "/TN", APP_NAME], capture_output=True, creationflags=NO_WINDOW)
        if enable:
            if elevated and is_admin():
                r = subprocess.run(["schtasks", "/Create", "/F", "/TN", APP_NAME, "/TR", cmd, "/SC", "ONLOGON", "/RL", "HIGHEST"],
                                   capture_output=True, creationflags=NO_WINDOW)
                if r.returncode == 0:
                    winreg.CloseKey(k)
                    return True
            winreg.SetValueEx(k, APP_NAME, 0, winreg.REG_SZ, cmd)
        winreg.CloseKey(k)
        return True
    except Exception:
        return False


# ---- recycle bin / explorer actions ------------------------------------------------
def trash(paths):
    """move to Recycle Bin. returns list of (path, error or None)"""
    res = []
    try:
        from send2trash import send2trash
    except ImportError:
        send2trash = None
    for p in paths:
        try:
            if send2trash:
                send2trash(os.path.normpath(p))
            elif IS_WIN:
                _shfile_delete(p)
            else:
                os.remove(p)
            res.append((p, None))
        except Exception as e:
            res.append((p, str(e)))
    return res


def _shfile_delete(path):
    import ctypes
    from ctypes import wintypes

    class OP(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]
    op = OP(None, 3, os.path.normpath(path) + "\0", None, 0x40 | 0x10 | 0x400, False, None, None)  # ALLOWUNDO|NOCONFIRM|NOERRORUI
    if ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op)) != 0:
        raise OSError("could not move to Recycle Bin")


def show_in_explorer(path):
    if IS_WIN:
        subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path)])


def open_path(path):
    if IS_WIN:
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def show_properties(path):
    if IS_WIN:
        import ctypes
        ctypes.windll.shell32.ShellExecuteW(None, "properties", os.path.normpath(path), None, None, 1)


def open_terminal(folder):
    if not IS_WIN:
        return
    try:
        subprocess.Popen(["wt.exe", "-d", folder])
    except OSError:
        subprocess.Popen(["cmd.exe", "/k"], cwd=folder, creationflags=0x00000010)


def copy_files_to_clipboard(paths):
    """so they can be pasted into Explorer / email"""
    if not IS_WIN:
        return
    lst = ",".join("'" + p.replace("'", "''") + "'" for p in paths)
    subprocess.Popen(["powershell", "-NoProfile", "-Command", f"Set-Clipboard -Path {lst}"], creationflags=NO_WINDOW)


# ---- tray icon (notification area / Action Center toasts) -----------------------------
class Tray:
    def __init__(self, items):
        """items: list of (label, callback or None for separator)"""
        self.icon = None
        self.items = items

    @staticmethod
    def available():
        try:
            import pystray  # noqa: F401
            from PIL import Image  # noqa: F401
            return True
        except Exception:
            return False

    def start(self):
        if self.icon or not self.available():
            return False
        import pystray
        from PIL import Image
        try:
            img = Image.open(resource_path("findit.png")).resize((64, 64))
            menu_items = []
            for label, cb in self.items:
                if cb is None:
                    menu_items.append(pystray.Menu.SEPARATOR)
                else:
                    menu_items.append(pystray.MenuItem(label, (lambda i, it, cb=cb: cb()),
                                                       default=(label.startswith("Show"))))
            self.icon = pystray.Icon(APP_NAME, img, "FindIt", pystray.Menu(*menu_items))
            self.icon.run_detached()
            return True
        except Exception:
            self.icon = None
            return False

    def notify(self, title, message):
        try:
            if self.icon:
                self.icon.notify(message, title)
        except Exception:
            pass

    def stop(self):
        ic, self.icon = self.icon, None
        if ic:
            try:
                ic.stop()
            except Exception:
                pass


# ---- global hotkey (Ctrl+Alt+Space) -------------------------------------------------
class Hotkey:
    def __init__(self, callback):
        self.callback = callback
        self.tid = None
        self.thread = None

    def start(self):
        if not IS_WIN or self.thread:
            return False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()
        return True

    def _run(self):
        import ctypes
        from ctypes import wintypes
        u = ctypes.windll.user32
        self.tid = ctypes.windll.kernel32.GetCurrentThreadId()
        if not u.RegisterHotKey(None, 1, 0x0001 | 0x0002 | 0x4000, 0x20):  # Alt+Ctrl+Space, no repeat
            return
        msg = wintypes.MSG()
        while u.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == 0x0312:
                self.callback()
        u.UnregisterHotKey(None, 1)

    def stop(self):
        if IS_WIN and self.tid:
            import ctypes
            ctypes.windll.user32.PostThreadMessageW(self.tid, 0x0012, 0, 0)
        self.thread, self.tid = None, None
