"""Thumbnails for any file: pictures, PDFs, videos, Office files...
Windows: asks Explorer's own thumbnail engine (same pictures you see in File Explorer).
Everywhere: pictures with Pillow, PDFs with PyMuPDF (if installed)."""
import os, threading
from PIL import Image, ImageOps
from engine import IS_WIN, IMG_EXT

SHELL_EXT = {".pdf", ".mp4", ".mkv", ".avi", ".mov", ".wmv", ".webm", ".flv", ".m4v", ".mpg", ".mpeg",
             ".docx", ".xlsx", ".pptx", ".doc", ".xls", ".ppt", ".odt", ".svg", ".heic", ".heif", ".psd",
             ".ai", ".eps", ".epub", ".mp3", ".flac", ".m4a", ".exe", ".lnk", ".ico", ".cr2", ".nef", ".dng"}
THUMB_EXT = (IMG_EXT | SHELL_EXT) if IS_WIN else (IMG_EXT | {".pdf"})
_local = threading.local()


def _pillow(path, size):
    im = Image.open(path)
    im.draft("RGB", (size * 2, size * 2))
    im = ImageOps.exif_transpose(im).convert("RGBA")
    im.thumbnail((size, size))
    return im


def _pdf(path, size):
    import fitz  # PyMuPDF
    doc = fitz.open(path)
    try:
        page = doc[0]
        r = page.rect
        zoom = size / max(r.width, r.height, 1)
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), alpha=False)
        return Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    finally:
        doc.close()


def _shell(path, size):
    """Windows Explorer thumbnail via IShellItemImageFactory"""
    import ctypes
    from ctypes import wintypes, byref, POINTER, c_void_p, WINFUNCTYPE, HRESULT, cast

    if not getattr(_local, "com", False):
        ctypes.windll.ole32.CoInitializeEx(None, 2)   # apartment threaded, once per worker thread
        _local.com = True

    class GUID(ctypes.Structure):
        _fields_ = [("Data1", ctypes.c_ulong), ("Data2", ctypes.c_ushort), ("Data3", ctypes.c_ushort),
                    ("Data4", ctypes.c_ubyte * 8)]

    class SIZE(ctypes.Structure):
        _fields_ = [("cx", ctypes.c_long), ("cy", ctypes.c_long)]

    class BITMAP(ctypes.Structure):
        _fields_ = [("bmType", ctypes.c_long), ("bmWidth", ctypes.c_long), ("bmHeight", ctypes.c_long),
                    ("bmWidthBytes", ctypes.c_long), ("bmPlanes", ctypes.c_ushort),
                    ("bmBitsPixel", ctypes.c_ushort), ("bmBits", c_void_p)]

    class BMIH(ctypes.Structure):
        _fields_ = [("biSize", ctypes.c_uint32), ("biWidth", ctypes.c_long), ("biHeight", ctypes.c_long),
                    ("biPlanes", ctypes.c_ushort), ("biBitCount", ctypes.c_ushort), ("biCompression", ctypes.c_uint32),
                    ("biSizeImage", ctypes.c_uint32), ("biXPels", ctypes.c_long), ("biYPels", ctypes.c_long),
                    ("biClrUsed", ctypes.c_uint32), ("biClrImportant", ctypes.c_uint32)]

    shell32, gdi32, user32 = ctypes.windll.shell32, ctypes.windll.gdi32, ctypes.windll.user32
    # IID_IShellItemImageFactory = {BCC18B79-BA16-442F-80C4-8A59C30C463B}
    iid = GUID(0xBCC18B79, 0xBA16, 0x442F, (ctypes.c_ubyte * 8)(0x80, 0xC4, 0x8A, 0x59, 0xC3, 0x0C, 0x46, 0x3B))
    shell32.SHCreateItemFromParsingName.argtypes = [wintypes.LPCWSTR, c_void_p, POINTER(GUID), POINTER(c_void_p)]
    shell32.SHCreateItemFromParsingName.restype = HRESULT
    gdi32.GetObjectW.argtypes = [c_void_p, ctypes.c_int, c_void_p]
    gdi32.GetDIBits.argtypes = [c_void_p, c_void_p, wintypes.UINT, wintypes.UINT, c_void_p, c_void_p, wintypes.UINT]
    gdi32.DeleteObject.argtypes = [c_void_p]
    user32.GetDC.restype = c_void_p
    user32.GetDC.argtypes = [c_void_p]
    user32.ReleaseDC.argtypes = [c_void_p, c_void_p]

    item = c_void_p()
    shell32.SHCreateItemFromParsingName(os.path.normpath(path), None, byref(iid), byref(item))
    if not item.value:
        raise OSError("no shell item")
    vtbl = cast(item, POINTER(POINTER(c_void_p)))[0]
    get_image = WINFUNCTYPE(HRESULT, c_void_p, SIZE, ctypes.c_uint, POINTER(c_void_p))(vtbl[3])
    release = WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl[2])
    hbmp = c_void_p()
    try:
        get_image(item, SIZE(size, size), 0x1 | 0x8, byref(hbmp))   # BIGGERSIZEOK | THUMBNAILONLY
        if not hbmp.value:
            raise OSError("no thumbnail")
        bm = BITMAP()
        gdi32.GetObjectW(hbmp, ctypes.sizeof(bm), byref(bm))
        w, h = bm.bmWidth, bm.bmHeight
        bmi = BMIH(ctypes.sizeof(BMIH), w, -h, 1, 32, 0, 0, 0, 0, 0, 0)   # top-down 32 bit
        buf = ctypes.create_string_buffer(w * h * 4)
        dc = user32.GetDC(None)
        try:
            gdi32.GetDIBits(dc, hbmp, 0, h, buf, byref(bmi), 0)
        finally:
            user32.ReleaseDC(None, dc)
        im = Image.frombuffer("RGBA", (w, h), bytes(buf), "raw", "BGRA", 0, 1)
        if im.getchannel("A").getextrema() == (0, 0):      # some thumbnails have no alpha
            im.putalpha(255)
        im.thumbnail((size, size))
        return im
    finally:
        if hbmp.value:
            gdi32.DeleteObject(hbmp)
        release(item)


def get_thumbnail(path, size):
    """-> RGBA PIL image no bigger than size x size, or None if this file has no thumbnail"""
    ext = os.path.splitext(path)[1].lower()
    tries = []
    if ext in IMG_EXT:
        tries.append(_pillow)
    if IS_WIN and ext in SHELL_EXT:
        tries.append(_shell)
    if ext == ".pdf":
        tries.append(_pdf)
    for fn in tries:
        try:
            im = fn(path, size)
            if im is not None:
                return im
        except Exception:
            continue
    return None
