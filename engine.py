"""FindIt engine: index (NTFS instant mode + fast parallel fallback), search syntax, settings, watcher."""
import os, sys, re, json, time, stat, marshal, threading, queue, string, fnmatch, datetime, platform, struct, heapq
from concurrent.futures import ThreadPoolExecutor

APP_NAME = "FindIt"
APP_VERSION = "2.0.0"
IS_WIN = platform.system() == "Windows"


def resource_path(name):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, name)


def data_dir():
    base = os.environ.get("APPDATA") if IS_WIN else os.path.expanduser("~")
    d = os.path.join(base or os.path.expanduser("~"), "FindIt" if IS_WIN else ".findit")
    os.makedirs(d, exist_ok=True)
    return d


# ----------------------------------------------------------------------------
# Settings
# ----------------------------------------------------------------------------
DEFAULTS = {
    "theme": "system", "live": True, "preview": True, "view": "details", "sidebar": True,
    "sort_key": "name", "sort_rev": False, "result_limit": 50000, "double_click": "open",
    "rescan": "auto", "rescan_hours": 12,
    "extra_locations": [], "skip_drives": [], "index_removable": True, "auto_new_drives": True,
    "exclude_dirs": [], "exclude_ext": [], "skip_hidden": False,
    "custom_types": {},
    "saved": [], "bookmarks": [], "history": [],
    "admin": False, "admin_asked": False, "start_with_windows": False, "start_minimized": False,
    "tray": True, "close_to_tray": False, "hotkey": True, "notify": True,
    "ui_style": "soft", "glass": "acrylic" if IS_WIN else "off", "opacity": 0.97, "geometry": "", "col_widths": {},
}


class Settings:
    def __init__(self, path=None):
        self.path = path or os.path.join(data_dir(), "settings.json")
        self.data = json.loads(json.dumps(DEFAULTS))
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                self.data.update(json.load(f))
        except Exception:
            pass

    def __getitem__(self, k):
        return self.data[k]

    def __setitem__(self, k, v):
        self.data[k] = v

    def save(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except Exception:
            pass

    def add_history(self, q):
        q = q.strip()
        if not q:
            return
        h = [x for x in self.data["history"] if x["q"] != q]
        h.insert(0, {"q": q, "t": int(time.time())})
        self.data["history"] = h[:100]
        self.save()


# ----------------------------------------------------------------------------
# File types
# ----------------------------------------------------------------------------
CATEGORIES = {
    "All": None,
    "Folders": "dir",
    "Documents": {".doc", ".docx", ".pdf", ".txt", ".xls", ".xlsx", ".csv", ".ppt", ".pptx", ".odt", ".rtf", ".md"},
    "Pictures": {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".svg", ".ico", ".heic", ".tif", ".tiff"},
    "Audio": {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".wma"},
    "Video": {".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv"},
    "Apps": {".exe", ".msi", ".apk", ".bat", ".lnk", ".cmd"},
    "Archives": {".zip", ".rar", ".7z", ".tar", ".gz", ".iso"},
}
SKIP_DIRS = {"$recycle.bin", "system volume information", "windows.old", "proc", "sys", "dev"}
IMG_EXT = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp", ".ico", ".tif", ".tiff"}
TEXT_EXT = {".txt", ".md", ".csv", ".log", ".json", ".xml", ".html", ".htm", ".css", ".js", ".py",
            ".ini", ".cfg", ".yml", ".yaml", ".bat", ".sh", ".sql", ".tsv", ".c", ".cpp", ".java", ".cs"}


def all_categories(custom=None):
    c = dict(CATEGORIES)
    for name, exts in (custom or {}).items():
        c[name] = {e if e.startswith(".") else "." + e for e in (x.strip().lower() for x in exts) if e}
    return c


def kind_of(ext, is_dir, cats=None):
    if is_dir:
        return "Folders"
    for name, s in (cats or CATEGORIES).items():
        if isinstance(s, set) and ext in s:
            return name
    return "Other"


def human_size(n):
    if n is None or n < 0:
        return ""
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.0f} {u}" if u == "B" else f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def human_date(t):
    if not t or t < 86400:
        return ""
    try:
        return datetime.datetime.fromtimestamp(t).strftime("%Y-%m-%d  %H:%M")
    except (OverflowError, OSError, ValueError):
        return ""


def type_name(ext, is_dir):
    return "Folder" if is_dir else (ext[1:].upper() + " file" if ext else "File")


def birth(st):
    return getattr(st, "st_birthtime", None) or st.st_ctime


def make_item(path, name, is_dir, st):
    ext = "" if is_dir else sys.intern(os.path.splitext(name)[1].lower())
    ln = name.lower()
    if ln == name:
        ln = name
    return (name, ln, path, is_dir, 0 if is_dir else st.st_size, st.st_mtime, ext, birth(st))


# ----------------------------------------------------------------------------
# Windows helpers: drives, admin, NTFS enumeration
# ----------------------------------------------------------------------------
def is_admin():
    if IS_WIN:
        try:
            import ctypes
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def list_drives():
    """-> list of dicts {letter, root, kind('fixed'|'removable'|'network'), label}"""
    out = []
    if not IS_WIN:
        return [{"letter": "/", "root": os.path.expanduser("~"), "kind": "fixed", "label": "Home"}]
    import ctypes
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    for i, ch in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        root = f"{ch}:\\"
        t = k32.GetDriveTypeW(root)
        kind = {3: "fixed", 2: "removable", 4: "network", 5: "removable"}.get(t)
        if not kind:
            continue
        buf = ctypes.create_unicode_buffer(261)
        fs = ctypes.create_unicode_buffer(261)
        label = ""
        try:
            if k32.GetVolumeInformationW(root, buf, 261, None, None, None, fs, 261):
                label = buf.value
        except Exception:
            pass
        out.append({"letter": ch, "root": root, "kind": kind, "label": label, "fs": fs.value})
    return out


def mft_scan(letter, should_stop=lambda: False):
    """Enumerate every file on an NTFS volume at once (needs administrator). -> dict frn -> (parent, name, attr)"""
    import ctypes
    from ctypes import wintypes
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateFileW.restype = ctypes.c_void_p
    k32.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    k32.DeviceIoControl.restype = wintypes.BOOL
    k32.DeviceIoControl.argtypes = [ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                                    ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
    k32.CloseHandle.argtypes = [ctypes.c_void_p]
    h = k32.CreateFileW(f"\\\\.\\{letter}:", 0x80000000, 3, None, 3, 0, None)
    if h is None or h == 0 or h == ctypes.c_void_p(-1).value:
        raise OSError(ctypes.get_last_error(), "cannot open volume (administrator needed)")
    try:
        ret = wintypes.DWORD(0)
        jbuf = ctypes.create_string_buffer(64)

        def query():
            return k32.DeviceIoControl(h, 0x000900f4, None, 0, jbuf, 64, ctypes.byref(ret), None)

        if not query():
            if ctypes.get_last_error() == 1179:  # journal not active -> create it
                cj = struct.pack("<QQ", 32 << 20, 4 << 20)
                k32.DeviceIoControl(h, 0x000900e7, cj, len(cj), None, 0, ctypes.byref(ret), None)
            if not query():
                raise OSError(ctypes.get_last_error(), "cannot read the NTFS journal")
        _jid, _first, nxt, _low, _max, _ms, _al = struct.unpack_from("<QqqqqQQ", jbuf.raw, 0)
        buf = ctypes.create_string_buffer(1 << 20)
        med = struct.pack("<Qqq", 0, 0, nxt)
        entries = {}
        unpack_head = struct.Struct("<IHHQQ").unpack_from
        MASK = 0x0000FFFFFFFFFFFF
        while not should_stop():
            ok = k32.DeviceIoControl(h, 0x000900b3, med, len(med), buf, len(buf), ctypes.byref(ret), None)
            if not ok:
                err = ctypes.get_last_error()
                if err == 38:  # end of file = done
                    break
                raise OSError(err, "NTFS enumeration failed")
            n = ret.value
            if n <= 8:
                break
            data = buf.raw[:n]
            nxt_frn = struct.unpack_from("<Q", data, 0)[0]
            off = 8
            while off < n:
                rec_len, major, _minor, frn, parent = unpack_head(data, off)
                if rec_len == 0:
                    break
                if major == 2:
                    attr = struct.unpack_from("<I", data, off + 52)[0]
                    nlen, noff = struct.unpack_from("<HH", data, off + 56)
                    name = data[off + noff: off + noff + nlen].decode("utf-16-le", "replace")
                    f = frn & MASK
                    if f >= 24:  # skip NTFS metafiles
                        entries[f] = (parent & MASK, name, attr)
                off += rec_len
            med = struct.pack("<Qqq", nxt_frn, 0, nxt)
        return entries
    finally:
        k32.CloseHandle(h)


def mft_paths(entries, letter, dir_excluded, skip_hidden):
    """Turn {frn: (parent, name, attr)} into {frn: path or None}"""
    root = f"{letter}:\\"
    paths = {}
    for frn in entries:
        if frn in paths:
            continue
        chain, cur, base = [], frn, None
        while True:
            if cur in paths:
                base = paths[cur]
                break
            ent = entries.get(cur)
            if ent is None:
                base = root if cur == 5 else None
                break
            chain.append(cur)
            cur = ent[0]
            if len(chain) > 4096:
                base = None
                break
        for node in reversed(chain):
            if base is None:
                paths[node] = None
                continue
            _p, name, attr = entries[node]
            is_dir = bool(attr & 0x10)
            if (skip_hidden and attr & 6) or (is_dir and dir_excluded(base, name)):
                base = None
                paths[node] = None
                continue
            base = base + name if base.endswith("\\") else base + "\\" + name
            paths[node] = base
    return paths


# ----------------------------------------------------------------------------
# Query language
# ----------------------------------------------------------------------------
_UNITS = {"": 1, "b": 1, "k": 1024, "kb": 1024, "m": 1 << 20, "mb": 1 << 20, "g": 1 << 30, "gb": 1 << 30, "t": 1 << 40, "tb": 1 << 40}
_TOKEN = re.compile(r'[!-]?(?:[A-Za-z]+:)?"[^"]*"|\S+')
_FUNCS = {"ext", "size", "dm", "modified", "dc", "created", "path", "in", "parent", "folder", "folders",
          "file", "files", "type", "name", "regex"}


def parse_size(v):
    v = v.strip().lower().replace(" ", "")
    if v == "empty":
        return 0, 0
    def one(s):
        m = re.fullmatch(r"([\d.]+)([a-z]*)", s)
        if not m or m.group(2) not in _UNITS:
            raise ValueError(f"bad size '{s}'")
        return int(float(m.group(1)) * _UNITS[m.group(2)])
    if ".." in v:
        a, b = v.split("..", 1)
        return (one(a) if a else 0), (one(b) if b else 1 << 60)
    m = re.match(r"(>=|<=|>|<|=)?(.*)", v)
    op, num = m.group(1) or "=", one(m.group(2))
    return {">": (num + 1, 1 << 60), ">=": (num, 1 << 60), "<": (0, num - 1), "<=": (0, num), "=": (num, num)}[op]


def _period(v, now):
    """-> (lo, hi) epoch seconds for a date word or absolute date"""
    d0 = datetime.datetime.combine(now.date(), datetime.time())
    day = datetime.timedelta(days=1)
    w = v.lower()
    ts = lambda d: d.timestamp()
    if w == "today":
        return ts(d0), ts(d0 + day)
    if w == "yesterday":
        return ts(d0 - day), ts(d0)
    if w == "thisweek":
        s = d0 - datetime.timedelta(days=d0.weekday())
        return ts(s), ts(s + 7 * day)
    if w == "week":
        return ts(d0 - 6 * day), ts(d0 + day)
    if w == "month":
        return ts(d0 - 29 * day), ts(d0 + day)
    if w == "year":
        return ts(d0 - 364 * day), ts(d0 + day)
    if w == "thismonth":
        s = d0.replace(day=1)
        e = (s + 32 * day).replace(day=1)
        return ts(s), ts(e)
    if w == "thisyear":
        return ts(d0.replace(month=1, day=1)), ts(d0.replace(year=d0.year + 1, month=1, day=1))
    m = re.fullmatch(r"(\d{4})(?:-(\d{1,2})(?:-(\d{1,2}))?)?", w)
    if not m:
        raise ValueError(f"bad date '{v}'")
    y, mo, d = int(m.group(1)), m.group(2), m.group(3)
    if d:
        s = datetime.datetime(y, int(mo), int(d)); return ts(s), ts(s + day)
    if mo:
        s = datetime.datetime(y, int(mo), 1); e = (s + 32 * day).replace(day=1); return ts(s), ts(e)
    return ts(datetime.datetime(y, 1, 1)), ts(datetime.datetime(y + 1, 1, 1))


def parse_date(v, now=None):
    now = now or datetime.datetime.now()
    v = v.strip()
    if ".." in v:
        a, b = v.split("..", 1)
        return (_period(a, now)[0] if a else 0), (_period(b, now)[1] if b else 1e18)
    m = re.match(r"(>=|<=|>|<|=)?(.*)", v)
    op, rest = m.group(1) or "=", m.group(2)
    lo, hi = _period(rest, now)
    return {">": (hi, 1e18), ">=": (lo, 1e18), "<": (0, lo), "<=": (0, hi), "=": (lo, hi)}[op]


class Query:
    """Compiles search text. Supports: words, "phrases", a|b, !not, *wild?cards, ext: size: dm: dc: path: folder: file: type: regex:"""

    def __init__(self, text, case=False, regex=False, in_path=False, cats=None):
        self.simple, self.preds, self.error = [], [], None
        self.cats = cats or CATEGORIES
        self.case, self.in_path = case, in_path
        text = text.strip()
        if not text:
            return
        flags = 0 if case else re.I
        if regex:
            try:
                rx = re.compile(text, flags)
            except re.error as e:
                self.error = f"Bad regex: {e}"
                self.preds.append(lambda it: False)
                return
            self.preds.append(lambda it: rx.search(it[2] if in_path else it[0]) is not None)
            return
        for tok in _TOKEN.findall(text):
            try:
                self._token(tok, flags)
            except ValueError as e:
                self.error = str(e)

    def _text_pred(self, t, flags, neg):
        case = self.case
        if "*" in t or "?" in t:
            rx = re.compile(fnmatch.translate(t), flags)
            p = (lambda it: rx.match(it[0]) is not None)
        else:
            tt = t if case else t.lower()
            use_path = self.in_path or "\\" in t or "/" in t
            if use_path:
                tt = tt.replace("/", os.sep) if os.sep == "\\" else tt.replace("\\", "/")
                p = (lambda it: tt in (it[2] if case else it[2].lower()))
            else:
                idx = 0 if case else 1
                p = (lambda it: tt in it[idx])
        return (lambda it: not p(it)) if neg else p

    def _token(self, tok, flags):
        neg = False
        if tok[0] == "!" or (tok[0] == "-" and len(tok) > 1):
            neg, tok = True, tok[1:]
        func, val = None, tok
        m = re.match(r"^([A-Za-z]+):(.*)$", tok)
        if m and m.group(1).lower() in _FUNCS:
            func, val = m.group(1).lower(), m.group(2)
        quoted = len(val) >= 2 and val[0] == '"' and val[-1] == '"'
        val = val.strip('"')
        if func is None:
            if not neg and not quoted and "|" not in val and "*" not in val and "?" not in val \
                    and "\\" not in val and "/" not in val and not self.in_path:
                self.simple.append(val if self.case else val.lower())
                return
            alts = [val] if quoted else [a for a in val.split("|") if a]
            if len(alts) <= 1:
                self.preds.append(self._text_pred(val, flags, neg))
            else:
                ps = [self._text_pred(a, flags, False) for a in alts]
                f = (lambda it, ps=ps: any(p(it) for p in ps))
                self.preds.append((lambda it, f=f: not f(it)) if neg else f)
            return
        if func == "ext":
            exts = {("." + e.lstrip(".")).lower() for e in re.split(r"[;,|]", val) if e}
            f = (lambda it: it[6] in exts)
        elif func == "size":
            lo, hi = parse_size(val)
            f = (lambda it: not it[3] and lo <= it[4] <= hi)
        elif func in ("dm", "modified"):
            lo, hi = parse_date(val)
            f = (lambda it: it[5] > 86400 and lo <= it[5] < hi)
        elif func in ("dc", "created"):
            lo, hi = parse_date(val)
            f = (lambda it: it[7] > 86400 and lo <= it[7] < hi)
        elif func in ("path", "in"):
            v = val if self.case else val.lower()
            f = (lambda it: v in (it[2] if self.case else it[2].lower()))
        elif func == "parent":
            v = val.lower()
            f = (lambda it: v in it[2][: max(0, len(it[2]) - len(it[0]))].lower())
        elif func in ("folder", "folders"):
            v = val.lower()
            f = (lambda it: it[3] and v in it[1])
        elif func in ("file", "files"):
            v = val.lower()
            f = (lambda it: (not it[3]) and v in it[1])
        elif func == "name":
            v = val.lower()
            f = (lambda it: v in it[1])
        elif func == "type":
            want = None
            for k in self.cats:
                if k.lower() == val.lower():
                    want = self.cats[k]
            if want is None:
                raise ValueError(f"unknown type '{val}'")
            f = (lambda it: it[3]) if want == "dir" else (lambda it: it[6] in want)
        elif func == "regex":
            rx = re.compile(val, flags)
            f = (lambda it: rx.search(it[0]) is not None)
        else:
            return
        self.preds.append((lambda it, f=f: not f(it)) if neg else f)


def highlight_terms(text):
    """plain words of a search (what to highlight in file names)"""
    out = []
    for tok in _TOKEN.findall(text or ""):
        if tok[0] in "!-" or re.match(r"^[A-Za-z]+:", tok) and tok.split(":")[0].lower() in _FUNCS:
            continue
        t = tok.strip('"').lower()
        if t and not any(c in t for c in "*?|\\/"):
            out.append(t)
    return out


SORT_KEYS = {
    "name": lambda i: i[1],
    "path": lambda i: os.path.dirname(i[2]).lower(),
    "size": lambda i: i[4],
    "type": lambda i: (i[6], i[1]),
    "date": lambda i: i[5],
    "created": lambda i: i[7],
}


# ----------------------------------------------------------------------------
# Index
# ----------------------------------------------------------------------------
class Index:
    def __init__(self, cache_path=None, cfg=None):
        self.map = {}
        self.lock = threading.Lock()
        self.scanning = False
        self.filling = False
        self.fill_progress = (0, 0)
        self.stop = False
        self.dirty = False
        self.cache_path = cache_path
        self.cfg = cfg if cfg is not None else Settings.__new__(Settings)
        self.mode = "standard"           # "ntfs" when instant mode was used
        self.cache_time = 0
        self.known_drives = set()
        self.configure()

    def __len__(self):
        return len(self.map)

    # ---- configuration (exclusions, locations)
    def configure(self):
        c = getattr(self.cfg, "data", {}) or {}
        self.skip_hidden = bool(c.get("skip_hidden"))
        names, prefixes = set(), []
        for d in c.get("exclude_dirs", []):
            d = d.strip()
            if not d:
                continue
            if "\\" in d or "/" in d or ":" in d:
                prefixes.append(os.path.normcase(os.path.normpath(d)).rstrip("\\/") + os.sep)
            else:
                names.add(d.lower())
        self.ex_names, self.ex_prefixes = names, tuple(prefixes)
        self.ex_ext = {("." + e.strip().lstrip(".")).lower() for e in c.get("exclude_ext", []) if e.strip()}

    def dir_excluded(self, parent, name):
        ln = name.lower()
        if ln in SKIP_DIRS or ln in self.ex_names:
            return True
        if self.ex_prefixes:
            full = os.path.normcase(os.path.join(parent, name)) + os.sep
            return any(full.startswith(p) for p in self.ex_prefixes)
        return False

    def excluded(self, path, name, is_dir, ext):
        if is_dir:
            return self.dir_excluded(os.path.dirname(path), name)
        if ext in self.ex_ext:
            return True
        if self.ex_names or self.ex_prefixes:
            return self._under_excluded(path)
        return False

    def _under_excluded(self, path):
        parts = os.path.normcase(path).replace("/", "\\" if IS_WIN else "/").split(os.sep)
        if any(p in self.ex_names for p in parts[:-1]):
            return True
        np_ = os.path.normcase(path)
        return any(np_.startswith(p) for p in self.ex_prefixes)

    def roots(self):
        c = getattr(self.cfg, "data", {}) or {}
        out = []
        skip = {s.upper() for s in c.get("skip_drives", [])}
        for d in list_drives():
            if d["letter"].upper() in skip:
                continue
            if d["kind"] == "fixed" or (d["kind"] == "removable" and c.get("index_removable", True)):
                out.append(d["root"])
        for p in c.get("extra_locations", []):
            if os.path.isdir(p) and p not in out:
                out.append(p)
        return out

    def new_drives(self):
        cur = {d["letter"]: d for d in list_drives()}
        new = [d for k, d in cur.items() if k not in self.known_drives]
        self.known_drives = set(cur)
        return new

    # ---- scanning
    def _walk(self, roots, out, progress=None, workers=8):
        q = queue.Queue()
        pending = [len(roots)]
        plock = threading.Lock()
        count = [0]
        results = []
        for r in roots:
            q.put(r)
        if not roots:
            return

        def worker():
            local = {}
            while True:
                d = q.get()
                if d is None:
                    break
                subs = []
                if not self.stop:
                    try:
                        with os.scandir(d) as it:
                            for e in it:
                                try:
                                    is_dir = e.is_dir(follow_symlinks=False)
                                    name = e.name
                                    st = e.stat(follow_symlinks=False)
                                    if self.skip_hidden and ((getattr(st, "st_file_attributes", 0) & 6) or
                                                             (not IS_WIN and name.startswith("."))):
                                        continue
                                    if is_dir:
                                        if self.dir_excluded(d, name):
                                            continue
                                    elif self.ex_ext and os.path.splitext(name)[1].lower() in self.ex_ext:
                                        continue
                                    local[e.path] = make_item(e.path, name, is_dir, st)
                                    if is_dir:
                                        subs.append(e.path)
                                except OSError:
                                    pass
                    except OSError:
                        pass
                    count[0] += 1
                    if progress and count[0] % 300 == 0:
                        progress(sum(len(x) for x in results) + len(local))
                with plock:
                    for s in subs:
                        q.put(s)
                    pending[0] += len(subs) - 1
                    done = pending[0] == 0
                if done:
                    for _ in range(workers):
                        q.put(None)
            results.append(local)

        ts = [threading.Thread(target=worker, daemon=True) for _ in range(workers)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        for r in results:
            out.update(r)

    def _scan_root(self, root, out, progress):
        """one root -> items. Uses NTFS enumeration when possible."""
        if IS_WIN and len(root) <= 3 and root[1:2] == ":" and is_admin():
            try:
                fs = next((d.get("fs") for d in list_drives() if d["root"].upper() == root[:3].upper()), "")
                if fs == "NTFS":
                    entries = mft_scan(root[0], lambda: self.stop)
                    paths = mft_paths(entries, root[0], self.dir_excluded, self.skip_hidden)
                    for frn, p in paths.items():
                        if not p:
                            continue
                        _par, name, attr = entries[frn]
                        is_dir = bool(attr & 0x10)
                        ext = "" if is_dir else sys.intern(os.path.splitext(name)[1].lower())
                        if not is_dir and ext in self.ex_ext:
                            continue
                        ln = name.lower()
                        out[p] = (name, name if ln == name else ln, p, is_dir, 0 if is_dir else -1, 0, ext, 0)
                    self.mode = "ntfs"
                    if progress:
                        progress(len(out))
                    return
            except Exception:
                pass  # fall back to the normal scan below
        self._walk([root], out, progress)

    def build(self, roots=None, progress=None):
        self.scanning, self.stop = True, False
        self.mode = "standard"
        out = {}
        try:
            self.configure()
            for r in (roots or self.roots()):
                if self.stop:
                    break
                self._scan_root(r, out, progress)
            if not self.stop:
                with self.lock:
                    self.map = out
                self.cache_time = time.time()
                self.dirty = True
        finally:
            self.scanning = False
        if progress:
            progress(len(out))
        if not self.stop:
            self.save_cache()

    def index_extra(self, root, progress=None):
        """add one more location (new drive / folder) without rebuilding everything"""
        out = {}
        self._scan_root(root, out, progress)
        with self.lock:
            self.map.update(out)
            self.dirty = True
        return len(out)

    def drop_prefix(self, prefix):
        pre = prefix.rstrip("\\/") + os.sep
        with self.lock:
            for k in [k for k in self.map if k.startswith(pre) or k == prefix]:
                del self.map[k]
            self.dirty = True

    def fill_details(self, progress=None, workers=8):
        """NTFS mode only knows names; read size/dates in the background."""
        with self.lock:
            todo = [p for p, it in self.map.items() if it[5] == 0]
        if not todo:
            return
        self.filling = True
        total, done = len(todo), 0

        def work(chunk):
            res = []
            for p in chunk:
                if self.stop:
                    break
                try:
                    res.append((p, os.lstat(p)))
                except OSError:
                    res.append((p, None))
            return res

        try:
            chunks = [todo[i:i + 3000] for i in range(0, total, 3000)]
            with ThreadPoolExecutor(workers) as ex:
                for res in ex.map(work, chunks):
                    with self.lock:
                        for p, st in res:
                            it = self.map.get(p)
                            if it is None:
                                continue
                            if st is None:
                                self.map[p] = it[:5] + (1,) + it[6:]
                            else:
                                self.map[p] = (it[0], it[1], it[2], it[3], 0 if it[3] else st.st_size,
                                               st.st_mtime, it[6], birth(st))
                    done += len(res)
                    self.fill_progress = (done, total)
                    self.dirty = True
                    if progress:
                        progress(done, total)
        finally:
            self.filling = False
        if not self.stop:
            self.save_cache()

    def ensure_details(self, items):
        """make sure the given items have size/date (used by duplicate finder)"""
        out = []
        for it in items:
            if it[5] == 0:
                try:
                    st = os.lstat(it[2])
                    it = (it[0], it[1], it[2], it[3], 0 if it[3] else st.st_size, st.st_mtime, it[6], birth(st))
                    with self.lock:
                        self.map[it[2]] = it
                except OSError:
                    continue
            out.append(it)
        return out

    # ---- live updates
    def add(self, path, deep=False):
        try:
            st = os.lstat(path)
        except OSError:
            return
        is_dir = stat.S_ISDIR(st.st_mode)
        name = os.path.basename(path.rstrip("\\/")) or path
        item = make_item(path, name, is_dir, st)
        if self.excluded(path, name, is_dir, item[6]):
            return
        extra = {}
        if is_dir and deep:
            self._walk([path], extra, workers=2)
        with self.lock:
            self.map[path] = item
            self.map.update(extra)
            self.dirty = True

    def remove(self, path):
        with self.lock:
            old = self.map.pop(path, None)
            if old is not None and old[3]:
                prefix = path.rstrip("\\/") + os.sep
                for k in [k for k in self.map if k.startswith(prefix)]:
                    del self.map[k]
            self.dirty = True

    # ---- cache
    def save_cache(self):
        if not self.cache_path:
            return
        try:
            tmp = f"{self.cache_path}.{os.getpid()}.tmp"
            with self.lock:
                items = list(self.map.values())
            with open(tmp, "wb") as f:
                marshal.dump({"v": 3, "time": self.cache_time or time.time(), "items": items}, f)
            os.replace(tmp, self.cache_path)
        except Exception:
            pass

    def load_cache(self):
        if not self.cache_path or not os.path.exists(self.cache_path):
            return False
        try:
            with open(self.cache_path, "rb") as f:
                d = marshal.load(f)
            if not isinstance(d, dict) or d.get("v") != 3:
                return False
            with self.lock:
                self.map = {it[2]: it for it in d["items"]}
            self.cache_time = d.get("time", 0)
            return True
        except Exception:
            return False

    def clear_cache(self):
        try:
            os.remove(self.cache_path)
        except Exception:
            pass

    # ---- search
    def search(self, text, category="All", case=False, regex=False, in_path=False, scope=None,
               sort_key="name", sort_rev=False, limit=5000, cats=None, cancel=None):
        """-> (rows, total, error)"""
        cats = cats or CATEGORIES
        with self.lock:
            items = list(self.map.values())
        q = Query(text, case, regex, in_path, cats)
        cat = cats.get(category)
        prefixes = []
        for s in (scope or []):
            p = os.path.normcase(os.path.normpath(s)).rstrip("\\/") + os.sep
            prefixes.append((p, s))
        terms = q.simple
        preds = q.preds
        if not cat and not prefixes and not preds:
            if not terms:
                matches = items
            elif case:
                matches = [it for it in items if all(t in it[0] for t in terms)]
            elif len(terms) == 1:
                t = terms[0]
                matches = [it for it in items if t in it[1]]
            else:
                matches = [it for it in items if all(t in it[1] for t in terms)]
        else:
            ci = 0 if case else 1
            pf = [p[0] for p in prefixes]
            is_dir_cat = cat == "dir"
            matches = []
            n = 0
            for it in items:
                n += 1
                if cancel is not None and not (n & 0x3FFF) and cancel():
                    return [], 0, None
                if cat is not None:
                    if is_dir_cat:
                        if not it[3]:
                            continue
                    elif it[6] not in cat:
                        continue
                if pf:
                    pn = os.path.normcase(it[2]) + os.sep
                    if not any(pn.startswith(x) for x in pf):
                        continue
                if terms and not all(t in it[ci] for t in terms):
                    continue
                if preds:
                    ok = True
                    for p in preds:
                        if not p(it):
                            ok = False
                            break
                    if not ok:
                        continue
                matches.append(it)
        total = len(matches)
        keyf = SORT_KEYS.get(sort_key, SORT_KEYS["name"])
        if total > limit:
            rows = (heapq.nlargest if sort_rev else heapq.nsmallest)(limit, matches, key=keyf)
        else:
            rows = sorted(matches, key=keyf, reverse=sort_rev)
        return rows, total, q.error


class Watcher:
    """Keeps the index current using Windows file-change notifications (watchdog).
    Events are collected and applied once a second, and noisy folders are ignored,
    so busy disks do not slow FindIt down."""

    NOISY = ("\\appdata\\local\\temp", "\\windows\\temp", "\\$recycle.bin", "\\system volume information",
             "\\.git\\", "\\windows\\prefetch", "\\inetcache", "\\windows\\logs", "\\$windows.~bt",
             "/.cache/", "/.git/")

    def __init__(self, index):
        self.index = index
        self.observer = None
        self.ops, self.mod = [], set()
        self.plock = threading.Lock()
        self._stop = threading.Event()
        self._flusher = None

    @staticmethod
    def available():
        try:
            import watchdog  # noqa: F401
            return True
        except ImportError:
            return False

    def _ignored(self, p):
        low = p.lower() + ("\\" if IS_WIN else "/")
        return any(n in low for n in self.NOISY)

    def _push(self, kind, a, b=None, is_dir=False):
        with self.plock:
            self.ops.append((kind, a, b, is_dir))

    def _flush(self):
        while not self._stop.wait(1.0):
            with self.plock:
                ops, mod = self.ops, self.mod
                self.ops, self.mod = [], set()
            for kind, a, b, is_dir in ops:
                if kind == "c":
                    self.index.add(a, deep=is_dir)
                elif kind == "d":
                    self.index.remove(a)
                else:
                    self.index.remove(a)
                    self.index.add(b, deep=is_dir)
            for p in mod:
                if p in self.index.map:
                    self.index.add(p)

    def start(self, roots=None):
        if self.observer or not self.available():
            return False
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
        outer = self

        class H(FileSystemEventHandler):
            def on_created(self, e):
                if not outer._ignored(e.src_path):
                    outer._push("c", e.src_path, None, e.is_directory)
            def on_deleted(self, e):
                if not outer._ignored(e.src_path):
                    outer._push("d", e.src_path)
            def on_moved(self, e):
                if not outer._ignored(e.src_path) or not outer._ignored(e.dest_path):
                    outer._push("m", e.src_path, e.dest_path, e.is_directory)
            def on_modified(self, e):
                if not e.is_directory and not outer._ignored(e.src_path):
                    with outer.plock:
                        outer.mod.add(e.src_path)

        obs = Observer()
        n = 0
        for r in roots or self.index.roots():
            try:
                obs.schedule(H(), r, recursive=True)
                n += 1
            except Exception:
                pass
        if not n:
            return False
        obs.daemon = True
        try:
            obs.start()
        except Exception:
            return False
        self.observer = obs
        self._stop.clear()
        self._flusher = threading.Thread(target=self._flush, daemon=True)
        self._flusher.start()
        return True

    def stop(self):
        obs, self.observer = self.observer, None
        self._stop.set()
        if obs:
            try:
                obs.stop()
                obs.join(timeout=2)
            except Exception:
                pass
